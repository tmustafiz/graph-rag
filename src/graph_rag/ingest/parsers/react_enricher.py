import re
from typing import TYPE_CHECKING

from ..models import CodeEntity

if TYPE_CHECKING:
    from tree_sitter import Node

_HOOK_RE = re.compile(r"^use[A-Z0-9]")

_JSX_ELEMENT_TYPES = {"jsx_element", "jsx_self_closing_element", "jsx_fragment"}
_JSX_OPENING_TYPES = {"jsx_opening_element", "jsx_self_closing_element"}

# Function-ish and class nodes whose entity may turn out to be a component.
_COMPONENT_NODE_TYPES = {
    "function_declaration",
    "generator_function_declaration",
    "arrow_function",
    "function_expression",
    "class_declaration",
    "abstract_class_declaration",
}
_CLASS_NODE_TYPES = {"class_declaration", "abstract_class_declaration"}
_PARAMETER_WRAPPERS = {"required_parameter", "optional_parameter"}


class ReactEnricher:
    """Second pass over a `.jsx` / `.tsx` (or `react`-importing `.js` / `.ts`)
    parse: retags a JSX-returning `function` / `class` `CodeEntity` as
    `kind="component"`, adds `RENDERS` edges to the components it mounts, and
    folds the hook calls and prop names it uses into `embed_text` / `signature`
    so `search_code("component that uses useAuth")` can hit.

    A rendered name is only linked when it resolves to a local definition or an
    import — unresolved and lowercase (`div`, `span`) tags are skipped, the
    same conservative policy as the parser's `calls`.
    """

    @staticmethod
    def applies(suffix: str, imports: list[str]) -> bool:
        if suffix in (".jsx", ".tsx"):
            return True
        return any(
            spec == "react" or spec.startswith(("react/", "react."))  # resolved specifiers
            for spec in imports
        )

    @classmethod
    def enrich(
        cls,
        root: "Node",
        content: bytes,
        entities: list[CodeEntity],
        *,
        module_qualified_name: str,
        local_top_level: set[str],
        import_bindings: dict[str, str],
    ) -> list[CodeEntity]:
        by_start_line: dict[int, CodeEntity] = {}
        for entity in entities:
            if entity.kind in ("function", "class") and entity.start_line is not None:
                by_start_line.setdefault(entity.start_line, entity)

        for node in cls._descendants(root):
            if node.type not in _COMPONENT_NODE_TYPES:
                continue
            entity = by_start_line.get(node.start_point[0] + 1)
            if entity is None or not cls._is_component(node, content):
                continue
            entity.kind = "component"
            entity.renders = cls._rendered_components(
                node,
                content,
                own_qualified_name=entity.qualified_name,
                module_qualified_name=module_qualified_name,
                local_top_level=local_top_level,
                import_bindings=import_bindings,
            )
            cls._fold_in_hooks_and_props(node, content, entity)
        return entities

    # -- component detection -------------------------------------------

    @classmethod
    def _is_component(cls, node: "Node", content: bytes) -> bool:
        if node.type in _CLASS_NODE_TYPES:
            return cls._extends_react_component(node, content) or cls._contains_jsx(node)
        return cls._contains_jsx(node)

    @classmethod
    def _contains_jsx(cls, node: "Node") -> bool:
        return any(child.type in _JSX_ELEMENT_TYPES for child in cls._descendants(node))

    @classmethod
    def _extends_react_component(cls, node: "Node", content: bytes) -> bool:
        heritage = next((child for child in node.children if child.type == "class_heritage"), None)
        if heritage is None:
            return False
        text = content[heritage.start_byte : heritage.end_byte].decode("utf-8", "replace")
        return "Component" in text

    # -- RENDERS edges ------------------------------------------------

    @classmethod
    def _rendered_components(
        cls,
        node: "Node",
        content: bytes,
        *,
        own_qualified_name: str,
        module_qualified_name: str,
        local_top_level: set[str],
        import_bindings: dict[str, str],
    ) -> list[str]:
        resolved: dict[str, None] = {}
        for element in cls._descendants(node):
            if element.type not in _JSX_OPENING_TYPES:
                continue
            name_node = next((child for child in element.children if child.is_named), None)
            if name_node is None or name_node.type != "identifier":
                continue  # namespaced (`<Foo.Bar>`) or member tags aren't resolved.
            name = cls._text(name_node, content)
            if not name[:1].isupper():
                continue  # lowercase host element (`div`, `span`).
            target = cls._resolve(name, module_qualified_name, local_top_level, import_bindings)
            if target is not None and target != own_qualified_name:
                resolved[target] = None
        return list(resolved)

    @staticmethod
    def _resolve(
        name: str,
        module_qualified_name: str,
        local_top_level: set[str],
        import_bindings: dict[str, str],
    ) -> str | None:
        if name in local_top_level:
            return f"{module_qualified_name}.{name}"
        return import_bindings.get(name)

    # -- hooks + props ----------------------------------------------

    @classmethod
    def _fold_in_hooks_and_props(cls, node: "Node", content: bytes, entity: CodeEntity) -> None:
        props = cls._prop_names(node, content)
        hooks = cls._hook_calls(node, content)
        additions: list[str] = []
        if props:
            additions.append(f"Props: {', '.join(props)}")
        if hooks:
            additions.append(f"Hooks: {', '.join(hooks)}")
        if not additions:
            return
        tail = "; ".join(additions)
        if entity.embed_text:
            entity.embed_text = f"{entity.embed_text.rstrip('. ')}. {tail}"
        else:
            entity.embed_text = tail
        entity.signature = f"{entity.signature} — {tail}" if entity.signature else tail

    @classmethod
    def _hook_calls(cls, node: "Node", content: bytes) -> list[str]:
        seen: dict[str, None] = {}
        for call in cls._descendants(node):
            if call.type != "call_expression":
                continue
            callee = call.child_by_field_name("function")
            if callee is None or callee.type != "identifier":
                continue
            name = cls._text(callee, content)
            if _HOOK_RE.match(name):
                seen[name] = None
        return list(seen)

    @classmethod
    def _prop_names(cls, node: "Node", content: bytes) -> list[str]:
        parameters = node.child_by_field_name("parameters")
        if parameters is None:
            return []
        first = next(
            (
                child
                for child in parameters.children
                if child.type in _PARAMETER_WRAPPERS
                or child.type in ("identifier", "object_pattern")
            ),
            None,
        )
        if first is None:
            return []
        target = first
        if target.type in _PARAMETER_WRAPPERS:
            target = next(
                (
                    child
                    for child in target.children
                    if child.type in ("identifier", "object_pattern")
                ),
                None,
            )
        if target is None:
            return []
        if target.type == "object_pattern":
            return cls._destructured_names(target, content)
        return cls._member_access_names(node, cls._text(target, content), content)

    @classmethod
    def _destructured_names(cls, pattern: "Node", content: bytes) -> list[str]:
        names: list[str] = []
        for child in pattern.children:
            if child.type == "shorthand_property_identifier_pattern":
                names.append(cls._text(child, content))
            elif child.type == "pair_pattern":
                key = child.child_by_field_name("key")
                if key is not None:
                    names.append(cls._text(key, content))
            elif child.type == "rest_pattern":
                identifier = next((kid for kid in child.children if kid.type == "identifier"), None)
                if identifier is not None:
                    names.append(f"...{cls._text(identifier, content)}")
        return names

    @classmethod
    def _member_access_names(cls, node: "Node", props_variable: str, content: bytes) -> list[str]:
        seen: dict[str, None] = {}
        for member in cls._descendants(node):
            if member.type != "member_expression":
                continue
            receiver = member.child_by_field_name("object")
            property_node = member.child_by_field_name("property")
            if (
                receiver is not None
                and property_node is not None
                and receiver.type == "identifier"
                and cls._text(receiver, content) == props_variable
            ):
                seen[cls._text(property_node, content)] = None
        return list(seen)

    # -- shared -----------------------------------------------------

    @staticmethod
    def _text(node: "Node", content: bytes) -> str:
        return content[node.start_byte : node.end_byte].decode("utf-8", "replace")

    @classmethod
    def _descendants(cls, node: "Node"):
        for child in node.children:
            yield child
            yield from cls._descendants(child)

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..dedupe import dedupe
from ..models import CamelRoute
from .camel_route_builder import bean_uri_ref
from .java_parser import _TYPE_KINDS, JavaParser

if TYPE_CHECKING:
    from tree_sitter import Node

_CAMEL_ROUTE_BUILDERS = {"RouteBuilder", "EndpointRouteBuilder", "AdviceWithRouteBuilder"}
# Camel Java-DSL step calls that just carry a predicate (recorded on the STEP edge).
_CAMEL_PREDICATE_STEPS = {"when", "filter", "validate"}
# Step calls whose first string argument is an endpoint URI (also a `to_uri`).
_CAMEL_URI_STEPS = {"to", "toD", "wireTap", "enrich", "pollEnrich", "recipientList"}


class CamelJavaDslExtractor(JavaParser):
    """Every `from(uri)....` chain inside a `RouteBuilder` subclass's
    `configure()` body, unwound step by step into a `CamelRoute` — the generic
    `CALLS` resolver skips fluent chains, so this walks them directly.

    Subclasses `JavaParser` only to share its tree-sitter helper suite
    (`_text`, `_collapse`, `_body_members`, `_supertypes`, `_resolve_type_name`,
    `_member_simple_name`); it is never registered as a parser.
    """

    @classmethod
    def extract(
        cls,
        type_nodes: list["Node"],
        content: bytes,
        imported_types: dict[str, str],
        same_file_types: dict[str, str],
        package: str,
        source_path: str,
    ) -> list[CamelRoute]:
        """Every `from(uri)....` chain inside a `RouteBuilder` subclass's
        `configure()` body, resolved step by step. `onException(...)` /
        `errorHandler(...)` at the `configure()` level contribute their
        exception FQNs to every route in that builder.
        """
        routes: list[CamelRoute] = []
        ordinal = 0

        for type_node in cls._all_type_declarations(type_nodes):
            extends, _implements = cls._supertypes(
                type_node, content, imported_types, same_file_types
            )
            if not any(
                supertype.rsplit(".", 1)[-1] in _CAMEL_ROUTE_BUILDERS for supertype in extends
            ):
                continue
            body = type_node.child_by_field_name("body")
            if body is None:
                continue
            configure = next(
                (
                    member
                    for member in cls._body_members(body)
                    if member.type == "method_declaration"
                    and cls._member_simple_name(member, content, "") == "configure"
                ),
                None,
            )
            configure_body = (
                configure.child_by_field_name("body") if configure is not None else None
            )
            if configure_body is None:
                continue

            chains = [
                cls._camel_chain(child.children[0], content)
                for child in configure_body.children
                if child.type == "expression_statement"
                and child.children
                and child.children[0].type == "method_invocation"
            ]
            on_exception: list[str] = []
            for chain in chains:
                if chain and chain[0][0] in ("onException", "errorHandler"):
                    on_exception.extend(
                        cls._resolve_type_name(name, imported_types, same_file_types)
                        for name in cls._camel_class_args(chain[0][1], content)
                    )
            for chain in chains:
                if not chain or chain[0][0] != "from":
                    continue
                route = cls._camel_route_from_chain(
                    chain, content, source_path, ordinal, imported_types, same_file_types
                )
                route.on_exception = dedupe(on_exception)
                routes.append(route)
                ordinal += 1
        return routes

    @classmethod
    def _all_type_declarations(cls, type_nodes: list["Node"]) -> list["Node"]:
        """`type_nodes` plus every nested / static-inner type, depth-first — a
        `RouteBuilder` is commonly a `@Component static class` inside a
        `@Configuration` class."""
        collected: list[Node] = []

        def walk(node: "Node") -> None:
            collected.append(node)
            body = node.child_by_field_name("body")
            if body is None:
                return
            for member in cls._body_members(body):
                if member.type in _TYPE_KINDS:
                    walk(member)

        for type_node in type_nodes:
            walk(type_node)
        return collected

    @classmethod
    def _camel_chain(cls, invocation: "Node", content: bytes) -> list[tuple[str, "Node | None"]]:
        """A fluent `a().b().c()` chain unwound into `[(a, args), (b, args), (c, args)]`
        in source order.
        """
        calls: list[tuple[str, Node | None]] = []
        node: Node | None = invocation
        while node is not None and node.type == "method_invocation":
            name_node = node.child_by_field_name("name")
            name = cls._text(name_node, content) if name_node is not None else ""
            calls.append((name, node.child_by_field_name("arguments")))
            node = node.child_by_field_name("object")
        calls.reverse()
        return calls

    @classmethod
    def _camel_route_from_chain(
        cls,
        chain: list[tuple[str, "Node | None"]],
        content: bytes,
        source_path: str,
        ordinal: int,
        imported_types: dict[str, str],
        same_file_types: dict[str, str],
    ) -> CamelRoute:
        from_uri = cls._camel_first_string(chain[0][1], content) or "unknown"
        route_id = f"{Path(source_path).stem}:{ordinal}"
        to_uris: list[str] = []
        steps: list[dict[str, Any]] = []
        step_index = 0
        # `choice()...when(pred).to(x)...otherwise().to(y)...end()` — a `to(...)`
        # reached only through a `choice` branch is conditional on that branch's
        # predicate. Nesting can't be reconstructed exactly from a flat call
        # chain: `.end()` closes *some* block EIP (`split` / `filter` / `doTry` /
        # …, not just `choice`) and `.endChoice()` is overloaded (end-branch vs
        # end-choice). So `choice_depth` is a best-effort counter and the
        # `conditional` flag is advisory — a nested block's `.end()` can zero it
        # early, under-reporting conditionality. That direction is deliberate:
        # `_GET_ROUTES` keeps every real `TO` target in `to_uris` regardless of
        # the flag (with `conditional_to_uris` alongside), so a mislabel
        # over-reports an always-taken destination rather than hiding one. (#161)
        choice_depth = 0
        branch_predicate: str | None = None
        for name, args in chain[1:]:
            if name in ("routeId", "id"):
                explicit = cls._camel_first_string(args, content)
                if explicit:
                    route_id = explicit
                continue
            if name == "choice":
                choice_depth += 1
                branch_predicate = None
            elif name in ("end", "endChoice") and choice_depth > 0:
                choice_depth -= 1
                # Reset on every decrement, not just at depth 0. A fully-correct
                # predicate for an outer branch after a nested `choice` closes
                # would need a predicate stack; "no label" beats the wrong one.
                branch_predicate = None
            if name in ("when", "filter"):
                branch_predicate = cls._collapse(cls._text(args, content)) if args else ""
            elif name == "otherwise":
                branch_predicate = "otherwise"
            conditional = choice_depth > 0 and name != "choice"
            step: dict[str, Any] = {"index": step_index, "kind": name}
            if conditional:
                step["conditional"] = True
                if branch_predicate is not None and "predicate" not in step:
                    step["predicate"] = branch_predicate
            if name in _CAMEL_URI_STEPS:
                uri = cls._camel_first_string(args, content)
                if uri:
                    step["uri"] = uri
                    to_uris.append(uri)
                    if uri.startswith("bean:"):
                        step["ref"] = bean_uri_ref(uri)
            elif name == "process":
                step["ref"] = cls._camel_ref_arg(args, content)
            elif name == "bean":
                step["ref"] = cls._camel_bean_ref(args, content, imported_types, same_file_types)
            elif name in _CAMEL_PREDICATE_STEPS:
                step["predicate"] = cls._collapse(cls._text(args, content)) if args else ""
            elif name in ("setHeader", "removeHeader", "setProperty"):
                header = cls._camel_first_string(args, content)
                if header:
                    step["name"] = header
            steps.append(step)
            step_index += 1

        summary = " -> ".join(
            step["kind"] + (f"({step['uri']})" if step.get("uri") else "") for step in steps
        )
        embed_text = f"Camel route {route_id}: from({from_uri})" + (
            f" -> {summary}" if summary else ""
        )
        return CamelRoute(
            route_id=route_id,
            from_uri=from_uri,
            source_path=source_path,
            ordinal=ordinal,
            to_uris=dedupe(to_uris),
            steps=steps,
            embed_text=embed_text,
        )

    @classmethod
    def _camel_first_string(cls, args: "Node | None", content: bytes) -> str | None:
        if args is None:
            return None
        for child in args.children:
            if child.type == "string_literal":
                text = cls._text(child, content)
                return text[1:-1] if len(text) >= 2 else text
        return None

    @classmethod
    def _camel_ref_arg(cls, args: "Node | None", content: bytes) -> str | None:
        """`process(...)` / bean reference: a string bean name, a `Type::method`
        reference, or `null` for a lambda / anonymous class.
        """
        if args is None:
            return None
        for child in args.children:
            if child.type == "string_literal":
                text = cls._text(child, content)
                return text[1:-1] if len(text) >= 2 else text
            if child.type == "method_reference":
                return cls._collapse(cls._text(child, content)).replace("::", ".")
        return None

    @classmethod
    def _camel_bean_ref(
        cls,
        args: "Node | None",
        content: bytes,
        imported_types: dict[str, str],
        same_file_types: dict[str, str],
    ) -> str | None:
        """`bean(OrderService.class, "handle")` → `OrderService.handle`;
        `bean("orderService")` → `orderService`.
        """
        if args is None:
            return None
        named = [child for child in args.children if child.is_named]
        if not named:
            return None
        first = named[0]
        if first.type == "string_literal":
            name = cls._text(first, content)
            head = name[1:-1] if len(name) >= 2 else name
        elif first.type == "class_literal":
            head = cls._collapse(cls._text(first, content)).removesuffix(".class")
        elif first.type in ("identifier", "field_access"):
            head = cls._collapse(cls._text(first, content)).removesuffix(".class")
        else:
            return None
        method = None
        if len(named) > 1 and named[1].type == "string_literal":
            method_text = cls._text(named[1], content)
            method = method_text[1:-1] if len(method_text) >= 2 else method_text
        return f"{head}.{method}" if method else head

    @classmethod
    def _camel_class_args(cls, args: "Node | None", content: bytes) -> list[str]:
        if args is None:
            return []
        names: list[str] = []
        for child in args.children:
            if child.type == "class_literal":
                names.append(cls._collapse(cls._text(child, content)).removesuffix(".class"))
        return names

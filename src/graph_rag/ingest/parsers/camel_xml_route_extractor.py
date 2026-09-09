from pathlib import Path
from xml.etree import ElementTree

from ..models import CamelRoute
from .camel_route_builder import CAMEL_URI_STEPS, CamelStepList
from .xml_namespace import local_name as _local

# element local-name → passthrough step kind for the flat step list. `choice` /
# `when` / `otherwise` are emitted with a synthetic `end` so the shape matches
# the Java DSL.
_PASSTHROUGH_STEPS = {
    "process",
    "bean",
    "split",
    "aggregate",
    "multicast",
    "loadBalance",
    "resequence",
    "delay",
    "throttle",
    "setBody",
    "setHeader",
    "removeHeader",
    "marshal",
    "unmarshal",
    "log",
    "loop",
    "filter",
    "convertBodyTo",
    "transform",
}
_PREDICATE_TAGS = ("simple", "xpath", "groovy", "jsonpath", "constant", "header", "method")


class CamelXmlRouteExtractor:
    """Extracts `CamelRoute`s from the Camel XML DSL — `<route>` elements found
    anywhere under the given root, whether the file is a standalone
    `<camelContext>` / `<routes>` or a Spring `<beans>` with an embedded
    `<camelContext>`. `<onException><exception>` FQNs under a `<camelContext>`
    attach to every route in it.

    Nested `<choice><when><simple/></when><otherwise/></choice>` is flattened to
    the same `choice / when / to... / otherwise / to... / end` step list the
    Java-DSL extractor produces (via the shared `CamelStepList`).
    """

    @classmethod
    def extract(cls, root: ElementTree.Element, source_path: str) -> list[CamelRoute]:
        stem = Path(source_path).stem
        contexts = cls._contexts(root)
        routes: list[CamelRoute] = []
        ordinal = 0
        for context in contexts:
            on_exception = cls._context_exceptions(context)
            for route_element in cls._descendants(context, "route"):
                route = cls._route(route_element, source_path, stem, ordinal)
                route.on_exception = on_exception
                routes.append(route)
                ordinal += 1
        return routes

    @classmethod
    def _contexts(cls, root: ElementTree.Element) -> list[ElementTree.Element]:
        if _local(root.tag) in ("camelContext", "routes"):
            return [root]
        if _local(root.tag) == "route":
            return [root]
        found = [
            element for element in root.iter() if _local(element.tag) in ("camelContext", "routes")
        ]
        return found or [root]

    @classmethod
    def _context_exceptions(cls, context: ElementTree.Element) -> list[str]:
        names: list[str] = []
        for handler in context:
            if _local(handler.tag) != "onException":
                continue
            for child in handler:
                if _local(child.tag) == "exception" and (child.text or "").strip():
                    names.append(child.text.strip())
        return names

    @classmethod
    def _route(
        cls, element: ElementTree.Element, source_path: str, stem: str, ordinal: int
    ) -> CamelRoute:
        route_id = element.get("id") or f"{stem}:{ordinal}"
        from_element = next((child for child in element if _local(child.tag) == "from"), None)
        from_uri = (from_element.get("uri") if from_element is not None else None) or "unknown"

        builder = CamelStepList()
        for child in element:
            if _local(child.tag) in ("from", "description"):
                continue
            cls._walk_step(child, builder, conditional=False, predicate=None)

        return builder.finish(
            route_id=route_id, from_uri=from_uri, source_path=source_path, ordinal=ordinal
        )

    @classmethod
    def _walk_step(
        cls,
        element: ElementTree.Element,
        builder: CamelStepList,
        *,
        conditional: bool,
        predicate: str | None,
    ) -> None:
        tag = _local(element.tag)

        if tag in CAMEL_URI_STEPS:
            builder.add_uri_step(
                tag, element.get("uri"), conditional=conditional, parent_predicate=predicate
            )
        elif tag == "bean":
            ref = element.get("ref") or element.get("beanType") or ""
            method = element.get("method")
            builder.add(
                "bean",
                conditional=conditional,
                parent_predicate=predicate,
                ref=f"{ref}.{method}" if method and ref else ref or None,
            )
        elif tag == "process":
            builder.add(
                "process",
                conditional=conditional,
                parent_predicate=predicate,
                ref=element.get("ref"),
            )
        elif tag == "choice":
            builder.add("choice", conditional=conditional, parent_predicate=predicate)
            for branch in element:
                cls._walk_step(branch, builder, conditional=True, predicate=predicate)
            builder.add("end", conditional=conditional, parent_predicate=predicate)
        elif tag in ("when", "filter"):
            branch_predicate = cls._predicate(element)
            builder.add(
                tag, conditional=conditional, parent_predicate=predicate, predicate=branch_predicate
            )
            for child in element:
                if _local(child.tag) not in _PREDICATE_TAGS:
                    cls._walk_step(child, builder, conditional=True, predicate=branch_predicate)
        elif tag == "otherwise":
            builder.add("otherwise", conditional=conditional, parent_predicate=predicate)
            for child in element:
                cls._walk_step(child, builder, conditional=True, predicate="otherwise")
        elif tag in _PASSTHROUGH_STEPS:
            extra = {"name": element.get("name")} if element.get("name") else {}
            builder.add(tag, conditional=conditional, parent_predicate=predicate, **extra)
            if tag in ("split", "multicast", "aggregate", "loadBalance", "loop"):
                for child in element:
                    if _local(child.tag) not in _PREDICATE_TAGS:
                        cls._walk_step(child, builder, conditional=conditional, predicate=predicate)

    @staticmethod
    def _predicate(element: ElementTree.Element) -> str:
        for child in element:
            if _local(child.tag) in _PREDICATE_TAGS and (child.text or "").strip():
                return child.text.strip()
        return ""

    @staticmethod
    def _descendants(element: ElementTree.Element, local_name: str) -> list[ElementTree.Element]:
        return [node for node in element.iter() if _local(node.tag) == local_name]

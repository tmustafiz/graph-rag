from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from ..models import CamelRoute

# element local-name → step kind for the flat step list. `choice` / `when` /
# `otherwise` are emitted with a synthetic `end` so the shape matches the Java DSL.
_URI_STEPS = {"to", "toD", "wireTap", "enrich", "pollEnrich", "recipientList"}
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


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


class CamelXmlRouteExtractor:
    """Extracts `CamelRoute`s from the Camel XML DSL — `<route>` elements found
    anywhere under the given root, whether the file is a standalone
    `<camelContext>` / `<routes>` or a Spring `<beans>` with an embedded
    `<camelContext>`. `<onException><exception>` FQNs under a `<camelContext>`
    attach to every route in it.

    Nested `<choice><when><simple/></when><otherwise/></choice>` is flattened to
    the same `choice / when / to... / otherwise / to... / end` step list the
    Java-DSL extractor produces.
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

        steps: list[dict[str, Any]] = []
        to_uris: list[str] = []
        counter = [0]
        for child in element:
            if _local(child.tag) in ("from", "description"):
                continue
            cls._walk_step(child, steps, to_uris, counter, conditional=False, predicate=None)

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
            to_uris=_dedupe(to_uris),
            steps=steps,
            embed_text=embed_text,
        )

    @classmethod
    def _walk_step(
        cls,
        element: ElementTree.Element,
        steps: list[dict[str, Any]],
        to_uris: list[str],
        counter: list[int],
        *,
        conditional: bool,
        predicate: str | None,
    ) -> None:
        tag = _local(element.tag)

        def add(kind: str, **extra: Any) -> None:
            step: dict[str, Any] = {"index": counter[0], "kind": kind, **extra}
            if conditional:
                step["conditional"] = True
                if predicate is not None and "predicate" not in step:
                    step["predicate"] = predicate
            steps.append(step)
            counter[0] += 1

        if tag in _URI_STEPS:
            uri = element.get("uri")
            uri_extra: dict[str, Any] = {}
            if uri:
                uri_extra["uri"] = uri
                to_uris.append(uri)
                if uri.startswith("bean:"):
                    uri_extra["ref"] = cls._bean_uri_ref(uri)
            add(tag, **uri_extra)
        elif tag == "bean":
            ref = element.get("ref") or element.get("beanType") or ""
            method = element.get("method")
            add("bean", ref=f"{ref}.{method}" if method and ref else ref or None)
        elif tag == "process":
            add("process", ref=element.get("ref"))
        elif tag == "choice":
            add("choice")
            for branch in element:
                cls._walk_step(
                    branch, steps, to_uris, counter, conditional=True, predicate=predicate
                )
            add("end")
        elif tag in ("when", "filter"):
            branch_predicate = cls._predicate(element)
            add(tag, predicate=branch_predicate)
            for child in element:
                if _local(child.tag) not in _PREDICATE_TAGS:
                    cls._walk_step(
                        child, steps, to_uris, counter, conditional=True, predicate=branch_predicate
                    )
        elif tag == "otherwise":
            add("otherwise")
            for child in element:
                cls._walk_step(
                    child, steps, to_uris, counter, conditional=True, predicate="otherwise"
                )
        elif tag in _PASSTHROUGH_STEPS:
            extra = {"name": element.get("name")} if element.get("name") else {}
            add(tag, **extra)
            if tag in ("split", "multicast", "aggregate", "loadBalance", "loop"):
                for child in element:
                    if _local(child.tag) not in _PREDICATE_TAGS:
                        cls._walk_step(
                            child,
                            steps,
                            to_uris,
                            counter,
                            conditional=conditional,
                            predicate=predicate,
                        )

    @staticmethod
    def _predicate(element: ElementTree.Element) -> str:
        for child in element:
            if _local(child.tag) in _PREDICATE_TAGS and (child.text or "").strip():
                return child.text.strip()
        return ""

    @staticmethod
    def _bean_uri_ref(uri: str) -> str:
        body = uri[len("bean:") :]
        name, _, query = body.partition("?")
        for option in query.split("&"):
            if option.startswith("method="):
                return f"{name}.{option[len('method=') :]}"
        return name

    @staticmethod
    def _descendants(element: ElementTree.Element, local_name: str) -> list[ElementTree.Element]:
        return [node for node in element.iter() if _local(node.tag) == local_name]


def _dedupe(items: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        if item:
            seen.setdefault(item, None)
    return list(seen)

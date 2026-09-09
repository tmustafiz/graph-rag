from pathlib import Path
from typing import Any

from ..dedupe import dedupe
from ..models import CamelRoute

_URI_STEPS = {"to", "toD", "wireTap", "enrich", "pollEnrich", "recipientList"}
_PASSTHROUGH_STEPS = {
    "process",
    "split",
    "aggregate",
    "multicast",
    "loadBalance",
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
_PREDICATE_KEYS = ("simple", "xpath", "groovy", "jsonpath", "constant", "expression")


class CamelYamlRouteExtractor:
    """Extracts `CamelRoute`s from the Camel YAML DSL.

    Handles the `- route:` list form and the flat `- from:` / `steps:` form; a
    step is `{to: "uri"}` or `{to: {uri: "uri"}}`. Nested `choice` / `when` /
    `otherwise` are flattened to the same step list the XML / Java extractors
    produce.
    """

    @classmethod
    def extract(cls, data: Any, source_path: str) -> list[CamelRoute]:
        stem = Path(source_path).stem
        entries = data if isinstance(data, list) else [data]
        routes: list[CamelRoute] = []
        ordinal = 0
        for entry in entries:
            spec = cls._route_spec(entry)
            if spec is None:
                continue
            routes.append(cls._route(spec, source_path, stem, ordinal))
            ordinal += 1
        return routes

    @staticmethod
    def _route_spec(entry: Any) -> dict[str, Any] | None:
        if not isinstance(entry, dict):
            return None
        if "route" in entry and isinstance(entry["route"], dict):
            return entry["route"]
        if "from" in entry:
            return entry
        return None

    @classmethod
    def _route(cls, spec: dict[str, Any], source_path: str, stem: str, ordinal: int) -> CamelRoute:
        route_id = str(spec.get("id") or spec.get("routeId") or f"{stem}:{ordinal}")
        from_spec = spec.get("from")
        if isinstance(from_spec, dict):
            from_uri = str(from_spec.get("uri") or "unknown")
            raw_steps = from_spec.get("steps") or spec.get("steps") or []
        else:
            from_uri = str(from_spec or "unknown")
            raw_steps = spec.get("steps") or []

        steps: list[dict[str, Any]] = []
        to_uris: list[str] = []
        counter = [0]
        for raw_step in raw_steps if isinstance(raw_steps, list) else []:
            cls._walk_step(raw_step, steps, to_uris, counter, conditional=False, predicate=None)

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
    def _walk_step(
        cls,
        raw_step: Any,
        steps: list[dict[str, Any]],
        to_uris: list[str],
        counter: list[int],
        *,
        conditional: bool,
        predicate: str | None,
    ) -> None:
        if not isinstance(raw_step, dict) or not raw_step:
            return
        kind, body = next(iter(raw_step.items()))

        def add(step_kind: str, **extra: Any) -> None:
            step: dict[str, Any] = {"index": counter[0], "kind": step_kind, **extra}
            if conditional:
                step["conditional"] = True
                if predicate is not None and "predicate" not in step:
                    step["predicate"] = predicate
            steps.append(step)
            counter[0] += 1

        if kind in _URI_STEPS:
            uri = body if isinstance(body, str) else (body or {}).get("uri")
            uri_extra: dict[str, Any] = {}
            if uri:
                uri_extra["uri"] = str(uri)
                to_uris.append(str(uri))
                if str(uri).startswith("bean:"):
                    uri_extra["ref"] = cls._bean_uri_ref(str(uri))
            add(kind, **uri_extra)
        elif kind == "bean":
            spec = body if isinstance(body, dict) else {}
            ref = spec.get("ref") or spec.get("beanType") or spec.get("method")
            method = spec.get("method")
            name = spec.get("ref") or spec.get("beanType")
            add("bean", ref=f"{name}.{method}" if name and method else (ref or None))
        elif kind == "process":
            spec = body if isinstance(body, dict) else {}
            add("process", ref=spec.get("ref"))
        elif kind == "choice":
            add("choice")
            spec = body if isinstance(body, dict) else {}
            for when in spec.get("when") or []:
                branch_predicate = cls._predicate(when)
                add("when", predicate=branch_predicate)
                for child in (when or {}).get("steps") or []:
                    cls._walk_step(
                        child, steps, to_uris, counter, conditional=True, predicate=branch_predicate
                    )
            otherwise = spec.get("otherwise")
            if otherwise is not None:
                add("otherwise")
                for child in (otherwise or {}).get("steps") or []:
                    cls._walk_step(
                        child, steps, to_uris, counter, conditional=True, predicate="otherwise"
                    )
            add("end")
        elif kind in _PASSTHROUGH_STEPS:
            spec = body if isinstance(body, dict) else {}
            extra = {"name": spec["name"]} if isinstance(spec, dict) and spec.get("name") else {}
            add(kind, **extra)
            if isinstance(spec, dict):
                for child in spec.get("steps") or []:
                    cls._walk_step(
                        child,
                        steps,
                        to_uris,
                        counter,
                        conditional=conditional,
                        predicate=predicate,
                    )

    @staticmethod
    def _predicate(when: Any) -> str:
        if not isinstance(when, dict):
            return ""
        for key in _PREDICATE_KEYS:
            value = when.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict) and isinstance(value.get("expression"), str):
                return value["expression"].strip()
        return ""

    @staticmethod
    def _bean_uri_ref(uri: str) -> str:
        body = uri[len("bean:") :]
        name, _, query = body.partition("?")
        for option in query.split("&"):
            if option.startswith("method="):
                return f"{name}.{option[len('method=') :]}"
        return name

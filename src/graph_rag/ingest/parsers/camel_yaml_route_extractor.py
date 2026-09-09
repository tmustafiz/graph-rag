from pathlib import Path
from typing import Any

from ..models import CamelRoute
from .camel_route_builder import CAMEL_URI_STEPS, CamelStepList

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
    produce (via the shared `CamelStepList`).
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

        builder = CamelStepList()
        for raw_step in raw_steps if isinstance(raw_steps, list) else []:
            cls._walk_step(raw_step, builder, conditional=False, predicate=None)

        return builder.finish(
            route_id=route_id, from_uri=from_uri, source_path=source_path, ordinal=ordinal
        )

    @classmethod
    def _walk_step(
        cls,
        raw_step: Any,
        builder: CamelStepList,
        *,
        conditional: bool,
        predicate: str | None,
    ) -> None:
        if not isinstance(raw_step, dict) or not raw_step:
            return
        kind, body = next(iter(raw_step.items()))

        if kind in CAMEL_URI_STEPS:
            uri = body if isinstance(body, str) else (body or {}).get("uri")
            builder.add_uri_step(
                kind, str(uri) if uri else None, conditional=conditional, parent_predicate=predicate
            )
        elif kind == "bean":
            spec = body if isinstance(body, dict) else {}
            ref = spec.get("ref") or spec.get("beanType") or spec.get("method")
            method = spec.get("method")
            name = spec.get("ref") or spec.get("beanType")
            builder.add(
                "bean",
                conditional=conditional,
                parent_predicate=predicate,
                ref=f"{name}.{method}" if name and method else (ref or None),
            )
        elif kind == "process":
            spec = body if isinstance(body, dict) else {}
            builder.add(
                "process", conditional=conditional, parent_predicate=predicate, ref=spec.get("ref")
            )
        elif kind == "choice":
            builder.add("choice", conditional=conditional, parent_predicate=predicate)
            spec = body if isinstance(body, dict) else {}
            for when in spec.get("when") or []:
                branch_predicate = cls._predicate(when)
                builder.add(
                    "when",
                    conditional=conditional,
                    parent_predicate=predicate,
                    predicate=branch_predicate,
                )
                for child in (when or {}).get("steps") or []:
                    cls._walk_step(child, builder, conditional=True, predicate=branch_predicate)
            otherwise = spec.get("otherwise")
            if otherwise is not None:
                builder.add("otherwise", conditional=conditional, parent_predicate=predicate)
                for child in (otherwise or {}).get("steps") or []:
                    cls._walk_step(child, builder, conditional=True, predicate="otherwise")
            builder.add("end", conditional=conditional, parent_predicate=predicate)
        elif kind in _PASSTHROUGH_STEPS:
            spec = body if isinstance(body, dict) else {}
            extra = {"name": spec["name"]} if isinstance(spec, dict) and spec.get("name") else {}
            builder.add(kind, conditional=conditional, parent_predicate=predicate, **extra)
            if isinstance(spec, dict):
                for child in spec.get("steps") or []:
                    cls._walk_step(child, builder, conditional=conditional, predicate=predicate)

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

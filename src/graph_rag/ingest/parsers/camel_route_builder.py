from typing import Any

from ..dedupe import dedupe
from ..models import CamelRoute

# Step kinds whose payload is an endpoint URI — also recorded as a `to_uri`.
# Identical for the XML and YAML DSLs (and the Java DSL's `_CAMEL_URI_STEPS`).
CAMEL_URI_STEPS: frozenset[str] = frozenset(
    {"to", "toD", "wireTap", "enrich", "pollEnrich", "recipientList"}
)


def bean_uri_ref(uri: str) -> str:
    """`bean:orderService?method=handle` -> `orderService.handle`; a bare
    `bean:orderService` -> `orderService`.
    """
    body = uri[len("bean:") :]
    name, _, query = body.partition("?")
    for option in query.split("&"):
        if option.startswith("method="):
            return f"{name}.{option[len('method=') :]}"
    return name


class CamelStepList:
    """Accumulates the flat, source-order step list that every Camel DSL
    extractor (XML, YAML, Java) produces, tracks the `to_uris` seen, and
    finalises into a `CamelRoute`. Only the *traversal* differs per DSL — the
    step shape, `conditional` / `predicate` tagging, `to_uris` collection, and
    route tail (`summary` / `embed_text` / `CamelRoute(...)`) do not.
    """

    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self.to_uris: list[str] = []
        self._index = 0

    def add(
        self,
        kind: str,
        *,
        conditional: bool = False,
        parent_predicate: str | None = None,
        **extra: Any,
    ) -> None:
        """Append one step. `extra` is merged verbatim (e.g. `ref`, `name`, or
        an explicit `predicate` for a `when` / `filter`). When `conditional`,
        the step is flagged and inherits `parent_predicate` unless `extra`
        already carries a `predicate`.
        """
        step: dict[str, Any] = {"index": self._index, "kind": kind, **extra}
        if conditional:
            step["conditional"] = True
            if parent_predicate is not None and "predicate" not in step:
                step["predicate"] = parent_predicate
        self.steps.append(step)
        self._index += 1

    def add_uri_step(
        self,
        kind: str,
        uri: str | None,
        *,
        conditional: bool = False,
        parent_predicate: str | None = None,
    ) -> None:
        extra: dict[str, Any] = {}
        if uri:
            extra["uri"] = str(uri)
            self.to_uris.append(str(uri))
            if str(uri).startswith("bean:"):
                extra["ref"] = bean_uri_ref(str(uri))
        self.add(kind, conditional=conditional, parent_predicate=parent_predicate, **extra)

    def finish(self, *, route_id: str, from_uri: str, source_path: str, ordinal: int) -> CamelRoute:
        summary = " -> ".join(
            step["kind"] + (f"({step['uri']})" if step.get("uri") else "") for step in self.steps
        )
        embed_text = f"Camel route {route_id}: from({from_uri})" + (
            f" -> {summary}" if summary else ""
        )
        return CamelRoute(
            route_id=route_id,
            from_uri=from_uri,
            source_path=source_path,
            ordinal=ordinal,
            to_uris=dedupe(self.to_uris),
            steps=self.steps,
            embed_text=embed_text,
        )

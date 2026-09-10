from typing import Any

from ..models import Annotation, CamelRoute, CodeEntity

_CONSUME_ANNOS = {"Consume", "Consumer"}
_PRODUCE_ANNOS = {"Produce", "EndpointInject", "Produced"}


class CamelAnnotationExtractor:
    """Camel POJO annotations that stand in for a route or an endpoint:

    * `@Consume(uri=)` / `@Consume` on a method → a one-step `CamelRoute` from
      that endpoint into the method (a `bean` step, so `CamelResolver` wires
      `INVOKES`).
    * `@Produce(uri=)` / `@EndpointInject(uri=)` on a field → a producer
      endpoint: `(:CodeEntity <owning type>)-[:PRODUCES_TO]->(:CamelEndpoint)`.
    """

    @classmethod
    def extract(
        cls,
        entities: list[CodeEntity],
        annotations: list[Annotation],
        start_ordinal: int,
        source_path: str,
    ) -> tuple[list[CamelRoute], list[dict[str, str]]]:
        methods = {entity.qualified_name: entity for entity in entities if entity.kind == "method"}

        routes: list[CamelRoute] = []
        produce_endpoints: list[dict[str, str]] = []
        ordinal = start_ordinal
        for annotation in annotations:
            uri = cls._uri(annotation.attributes)
            if annotation.name in _CONSUME_ANNOS and annotation.target == "method":
                method = methods.get(annotation.owner_qualified_name)
                if method is None or method.parent_qualified_name is None or not uri:
                    continue
                type_simple = method.parent_qualified_name.rsplit(".", 1)[-1]
                routes.append(
                    CamelRoute(
                        route_id=f"{method.name}@Consume",
                        from_uri=uri,
                        source_path=source_path,
                        ordinal=ordinal,
                        steps=[{"index": 0, "kind": "bean", "ref": f"{type_simple}.{method.name}"}],
                        embed_text=f"Camel @Consume route: from({uri}) -> {method.name}",
                    )
                )
                ordinal += 1
            elif annotation.name in _PRODUCE_ANNOS and annotation.target == "field" and uri:
                producer_qn = annotation.owner_qualified_name.split("#", 1)[0]
                produce_endpoints.append({"uri": uri, "producer_qn": producer_qn})
        return routes, produce_endpoints

    @staticmethod
    def _uri(attributes: dict[str, Any]) -> str | None:
        for key in ("uri", "value"):
            raw = attributes.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        return None

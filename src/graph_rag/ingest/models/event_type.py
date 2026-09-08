from pydantic import BaseModel, Field


class EventType(BaseModel):
    """An application-event class that is published and/or consumed in-process.

    Event-driven flows are a hidden call graph: an
    `ApplicationEventPublisher.publishEvent(new OrderPlacedEvent(...))` and an
    `@EventListener void on(OrderPlacedEvent e)` never reference each other in
    source. This node bridges them —
    `(publisher:CodeEntity)-[:PUBLISHES]->(:EventType)-[:CONSUMED_BY]->(listener:CodeEntity)`.

    `fqn` is import-resolved where possible, otherwise the simple type name; it
    is the graph key, so publisher and listener sides are normalized to a
    single canonical `fqn` per simple name by the `MessageFlowExtractor`.
    `published_by` / `consumed_by` are handler method `qualified_name`s.
    """

    fqn: str
    simple_name: str
    published_by: list[str] = Field(default_factory=list)
    consumed_by: list[str] = Field(default_factory=list)

from pydantic import BaseModel, Field


class MessageFlowResult(BaseModel):
    """Publisher ↔ consumer flow for one event type or broker destination, from
    `get_message_flows` — the hidden call graph between code that never
    references the other side directly.
    """

    kind: str  # "event" | "destination"
    name: str  # EventType.fqn / EventType.simple_name, or Destination.name
    broker: str | None = None  # for a destination: kafka / rabbit / jms / sqs / …
    publishers: list[str] = Field(default_factory=list)  # CodeEntity qualified_names
    consumers: list[str] = Field(default_factory=list)  # CodeEntity qualified_names

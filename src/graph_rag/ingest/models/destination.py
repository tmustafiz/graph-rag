from pydantic import BaseModel, Field, computed_field


class Destination(BaseModel):
    """A message-broker destination — a Kafka topic, a Rabbit queue/exchange, a
    JMS destination, an SQS queue — named by a literal string in the source.

    `(:CodeEntity)-[:PRODUCES_TO]->(:Destination)-[:CONSUMED_BY]->(:CodeEntity)`
    recovers the producer↔consumer call graph that a `KafkaTemplate.send(...)` /
    `@KafkaListener(topics=...)` pair hides. `broker` is `kafka` / `rabbit` /
    `jms` / `sqs` / `unknown`; `id` (`<broker>:<name>`) is the graph key.
    `produced_by` / `consumed_by` are handler method `qualified_name`s.
    """

    name: str
    broker: str
    produced_by: list[str] = Field(default_factory=list)
    consumed_by: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        return f"{self.broker}:{self.name}"

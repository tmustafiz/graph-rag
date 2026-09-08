from typing import Any

from ..models import Annotation, CodeEntity, Destination, EventType

# broker-listener annotation simple name → (broker, attribute keys holding the
# destination string(s), in priority order).
_BROKER_LISTENERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "KafkaListener": ("kafka", ("topics", "topicPattern", "id")),
    "RabbitListener": ("rabbit", ("queues", "value")),
    "JmsListener": ("jms", ("destination",)),
    "SqsListener": ("sqs", ("value", "queueNames")),
    "StreamListener": ("stream", ("value", "target")),
}
_EVENT_LISTENER_ANNOS = {"EventListener", "TransactionalEventListener"}


class MessageFlowExtractor:
    """Assembles `EventType` / `Destination` nodes from a parsed `.java` file.

    In-process events (`@EventListener` methods and
    `ApplicationEventPublisher.publishEvent(...)` call sites) come pre-resolved
    from `JavaParser` as `message_sites` — it has the imports and method nodes
    needed to name the event type. Broker listeners
    (`@KafkaListener(topics=)` / `@RabbitListener(queues=)` /
    `@JmsListener(destination=)` / `@SqsListener` / `@StreamListener`) are read
    straight off the `Annotation` list since their destination is a literal.

    Publisher and listener sides are keyed to one canonical `EventType.fqn` per
    simple name, so a publisher that resolved a full FQN still links to a
    listener that only had the simple name.
    """

    @classmethod
    def extract(
        cls,
        entities: list[CodeEntity],
        annotations: list[Annotation],
        message_sites: list[dict[str, Any]],
    ) -> tuple[list[EventType], list[Destination]]:
        events = cls._event_types(message_sites)
        destinations = cls._destinations(annotations, message_sites)
        return events, destinations

    # -- in-process events --

    @classmethod
    def _event_types(cls, message_sites: list[dict[str, Any]]) -> list[EventType]:
        # simple name → canonical fqn (longest / most-qualified wins)
        canonical: dict[str, str] = {}
        for site in message_sites:
            if site.get("kind") not in ("event-listener", "event-publish"):
                continue
            fqn = site.get("event_type")
            if not fqn:
                continue
            simple = cls._simple_name(fqn)
            if simple not in canonical or len(fqn) > len(canonical[simple]):
                canonical[simple] = fqn

        by_simple: dict[str, EventType] = {}
        for site in message_sites:
            kind = site.get("kind")
            if kind not in ("event-listener", "event-publish"):
                continue
            fqn = site.get("event_type")
            if not fqn:
                continue
            simple = cls._simple_name(fqn)
            event = by_simple.setdefault(
                simple, EventType(fqn=canonical.get(simple, fqn), simple_name=simple)
            )
            method_qn = site["enclosing_qn"]
            bucket = event.consumed_by if kind == "event-listener" else event.published_by
            if method_qn not in bucket:
                bucket.append(method_qn)
        return list(by_simple.values())

    # -- broker destinations --

    @classmethod
    def _destinations(
        cls, annotations: list[Annotation], message_sites: list[dict[str, Any]]
    ) -> list[Destination]:
        by_key: dict[tuple[str, str], Destination] = {}

        def dest(broker: str, name: str) -> Destination:
            return by_key.setdefault((broker, name), Destination(name=name, broker=broker))

        for annotation in annotations:
            if annotation.target.startswith("param:"):
                continue
            spec = _BROKER_LISTENERS.get(annotation.name)
            if spec is None:
                continue
            broker, keys = spec
            for name in cls._first_string_list(annotation.attributes, keys):
                target = dest(broker, name)
                if annotation.owner_qualified_name not in target.consumed_by:
                    target.consumed_by.append(annotation.owner_qualified_name)

        for site in message_sites:
            if site.get("kind") != "broker-produce":
                continue
            name = site.get("destination")
            if not name:
                continue
            target = dest(site.get("broker") or "unknown", name)
            if site["enclosing_qn"] not in target.produced_by:
                target.produced_by.append(site["enclosing_qn"])

        return list(by_key.values())

    # -- helpers --

    @staticmethod
    def _first_string_list(attributes: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
        for key in keys:
            raw = attributes.get(key)
            if raw is None:
                continue
            items = raw if isinstance(raw, (list, tuple)) else [raw]
            values = [str(item).strip() for item in items if str(item).strip()]
            if values:
                return values
        return []

    @staticmethod
    def _simple_name(fqn: str) -> str:
        return fqn.rsplit(".", 1)[-1].split("<", 1)[0].strip()

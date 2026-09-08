"""Spring events & messaging: `MessageFlowExtractor` output on a parsed `.java`
file (event listeners, publish sites, broker listeners, template sends).
"""

from pathlib import Path

from graph_rag.ingest.parsers.java_parser import JavaParser

_ORDERS = """\
package com.acme.orders;

import org.springframework.context.ApplicationEventPublisher;
import org.springframework.context.event.EventListener;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Service;

@Service
public class OrderService {

    private final ApplicationEventPublisher publisher;
    private final KafkaTemplate<String, Order> kafkaTemplate;

    public OrderService(ApplicationEventPublisher publisher, KafkaTemplate<String, Order> kt) {
        this.publisher = publisher;
        this.kafkaTemplate = kt;
    }

    public void place(Order order) {
        publisher.publishEvent(new OrderPlacedEvent(order));
        kafkaTemplate.send("orders.outbound", order.id());
    }

    @EventListener
    public void onOrderPlaced(OrderPlacedEvent event) {
        // audit
    }

    @KafkaListener(topics = {"orders.inbound", "orders.dlq"})
    public void consume(String payload) {
        // handle
    }
}
"""

_EXPLICIT_CLASSES = """\
package com.acme.orders;

import org.springframework.transaction.event.TransactionalEventListener;

public class ShipmentListener {

    @TransactionalEventListener(classes = OrderPlacedEvent.class)
    public void onCommit(Object event) {}
}
"""


def _parse(tmp_path: Path, name: str, body: str):
    package_dir = tmp_path / "com" / "acme" / "orders"
    package_dir.mkdir(parents=True, exist_ok=True)
    path = package_dir / name
    path.write_text(body)
    return JavaParser().parse(path)


def test_event_listener_param_type_and_publish_site_link_via_one_event_type(
    tmp_path: Path,
) -> None:
    document = _parse(tmp_path, "OrderService.java", _ORDERS)
    events = {event.simple_name: event for event in document.event_types}

    placed = events["OrderPlacedEvent"]
    assert placed.published_by == ["com.acme.orders.OrderService.place(Order)"]
    assert placed.consumed_by == ["com.acme.orders.OrderService.onOrderPlaced(OrderPlacedEvent)"]


def test_kafka_listener_topics_become_a_consumed_destination(tmp_path: Path) -> None:
    document = _parse(tmp_path, "OrderService.java", _ORDERS)
    by_name = {destination.name: destination for destination in document.destinations}

    inbound = by_name["orders.inbound"]
    assert inbound.broker == "kafka"
    assert inbound.consumed_by == ["com.acme.orders.OrderService.consume(String)"]
    assert by_name["orders.dlq"].broker == "kafka"


def test_kafka_template_send_literal_topic_is_a_produced_destination(tmp_path: Path) -> None:
    document = _parse(tmp_path, "OrderService.java", _ORDERS)
    by_name = {destination.name: destination for destination in document.destinations}

    outbound = by_name["orders.outbound"]
    assert outbound.broker == "kafka"
    assert outbound.produced_by == ["com.acme.orders.OrderService.place(Order)"]


def test_transactional_event_listener_reads_the_classes_attribute(tmp_path: Path) -> None:
    document = _parse(tmp_path, "ShipmentListener.java", _EXPLICIT_CLASSES)
    events = {event.simple_name: event for event in document.event_types}

    assert events["OrderPlacedEvent"].consumed_by == [
        "com.acme.orders.ShipmentListener.onCommit(Object)"
    ]

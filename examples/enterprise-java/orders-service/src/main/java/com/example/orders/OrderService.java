package com.example.orders;

import org.springframework.context.ApplicationEventPublisher;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class OrderService {

    private final ApplicationEventPublisher publisher;
    private final KafkaTemplate<String, String> kafkaTemplate;
    private final InventoryClient inventoryClient;

    public OrderService(
            ApplicationEventPublisher publisher,
            KafkaTemplate<String, String> kafkaTemplate,
            InventoryClient inventoryClient) {
        this.publisher = publisher;
        this.kafkaTemplate = kafkaTemplate;
        this.inventoryClient = inventoryClient;
    }

    @Transactional
    public void place(String orderId, String sku) {
        inventoryClient.getItem(sku);
        publisher.publishEvent(new OrderPlacedEvent(orderId));
        kafkaTemplate.send("orders.outbound", orderId);
    }

    /** Invoked by the Camel route as bean(OrderService.class, "enrich"). */
    public String enrich(String body) {
        return body.trim();
    }
}

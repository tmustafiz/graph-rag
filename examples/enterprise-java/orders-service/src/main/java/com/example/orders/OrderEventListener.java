package com.example.orders;

import org.springframework.context.event.EventListener;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Component
public class OrderEventListener {

    @EventListener
    public void onOrderPlaced(OrderPlacedEvent event) {
        // audit
    }

    @KafkaListener(topics = "orders.inbound")
    public void consume(String payload) {
        // handle
    }
}

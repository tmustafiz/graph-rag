package com.example.orders;

/** Published in-process when an order is placed; consumed by OrderEventListener. */
public class OrderPlacedEvent {
    private final String orderId;

    public OrderPlacedEvent(String orderId) {
        this.orderId = orderId;
    }

    public String orderId() {
        return orderId;
    }
}

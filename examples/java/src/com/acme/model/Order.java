package com.acme.model;

/** A single customer order. */
public record Order(String id, int quantity, boolean priority) {

    /** True when this order should jump the queue. */
    public boolean isExpedited() {
        return priority || quantity > 100;
    }
}

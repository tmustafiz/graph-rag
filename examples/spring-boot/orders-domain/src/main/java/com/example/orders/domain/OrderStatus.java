package com.example.orders.domain;

/** Lifecycle state of an {@link Order}. */
public enum OrderStatus {
    NEW,
    PAID,
    SHIPPED,
    CANCELLED
}

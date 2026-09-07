package com.example.orders.api;

/** Outbound "order created" notification — implemented by an XML-wired bean. */
public interface NotificationGateway {

    void notifyCreated(Long orderId);
}

package com.example.orders.api;

import java.util.List;

/** Request body for `POST /api/orders`. */
public record CreateOrderRequest(Long customerId, List<String> skus) {
}

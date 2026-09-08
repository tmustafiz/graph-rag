package com.example.orders;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;

/** Declarative HTTP client -> resolves to inventory-service's InventoryController. */
@FeignClient(name = "inventory", path = "/inventory")
public interface InventoryClient {

    @GetMapping("/items/{sku}")
    String getItem(@PathVariable String sku);
}

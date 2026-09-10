package com.example.inventory;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** The route the orders-service @FeignClient resolves to. */
@RestController
@RequestMapping("/inventory")
public class InventoryController {

    private final InventoryMapper mapper;

    public InventoryController(InventoryMapper mapper) {
        this.mapper = mapper;
    }

    @GetMapping("/items/{sku}")
    public String getItem(@PathVariable String sku) {
        return mapper.findBySku(sku);
    }
}

package com.example.orders.api;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/** Binds the `orders.*` subtree of application.yml. */
@Component
@ConfigurationProperties(prefix = "orders")
public class OrderProperties {

    private boolean notifyOnCreate = true;
    private int maxLinesPerOrder = 100;

    public boolean isNotifyOnCreate() {
        return notifyOnCreate;
    }

    public void setNotifyOnCreate(boolean notifyOnCreate) {
        this.notifyOnCreate = notifyOnCreate;
    }

    public int getMaxLinesPerOrder() {
        return maxLinesPerOrder;
    }

    public void setMaxLinesPerOrder(int maxLinesPerOrder) {
        this.maxLinesPerOrder = maxLinesPerOrder;
    }
}

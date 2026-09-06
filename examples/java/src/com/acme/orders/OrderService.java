package com.acme.orders;

import com.acme.model.Order;
import java.util.ArrayList;
import java.util.List;
import static java.util.Objects.requireNonNull;

/**
 * Accepts orders and routes the expedited ones to a priority lane.
 */
public class OrderService implements Runnable {

    private final List<Order> accepted = new ArrayList<>();
    private int rejected = 0;

    /** Validate, then record the order. */
    public void submit(Order order) {
        requireNonNull(order);
        if (this.accepts(order)) {
            accepted.add(order);
        } else {
            rejected++;
        }
    }

    private boolean accepts(Order order) {
        return order.isExpedited() || accepted.size() < 500;
    }

    /** Overload that submits several orders in one call. */
    public void submit(List<Order> orders) {
        for (Order order : orders) {
            submit(order);
        }
    }

    @Override
    public void run() {
        Order sample = new Order("demo", 1, false);
        this.submit(sample);
    }

    /** Nested view object — exercises the CONTAINS hierarchy. */
    static final class Stats {
        int total() {
            return 0;
        }
    }

    enum Lane { STANDARD, PRIORITY }
}

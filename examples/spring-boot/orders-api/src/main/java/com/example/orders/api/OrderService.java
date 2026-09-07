package com.example.orders.api;

import com.example.orders.domain.Order;
import com.example.orders.domain.OrderRepository;
import com.example.orders.domain.OrderStatus;
import java.util.List;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
public class OrderService {

    private final OrderRepository orderRepository;
    private final OrderProperties properties;

    /** {@link NotificationGateway} is wired from legacy-context.xml, not an annotation. */
    @Autowired
    private NotificationGateway notificationGateway;

    public OrderService(OrderRepository orderRepository, OrderProperties properties) {
        this.orderRepository = orderRepository;
        this.properties = properties;
    }

    public Order findById(Long id) {
        return orderRepository.findById(id).orElseThrow();
    }

    public List<Order> listForCustomer(Long customerId) {
        if (customerId == null) {
            return orderRepository.findAll();
        }
        return orderRepository.findByCustomerIdAndStatusOrderByCreatedAtDesc(customerId, OrderStatus.NEW);
    }

    public Order create(CreateOrderRequest request) {
        Order order = new Order();
        Order saved = orderRepository.save(order);
        if (properties.isNotifyOnCreate()) {
            notificationGateway.notifyCreated(saved.getId());
        }
        return saved;
    }
}

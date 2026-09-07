package com.example.orders.api;

/**
 * A plain class (no `@Component`) — it becomes a bean only through the
 * `<bean id="notificationGateway" .../>` entry in legacy-context.xml, and
 * {@link OrderService}'s `@Autowired NotificationGateway` resolves to it.
 */
public class EmailNotificationGateway implements NotificationGateway {

    private final String fromAddress;

    public EmailNotificationGateway(String fromAddress) {
        this.fromAddress = fromAddress;
    }

    @Override
    public void notifyCreated(Long orderId) {
        // send an email from `fromAddress` ...
    }
}

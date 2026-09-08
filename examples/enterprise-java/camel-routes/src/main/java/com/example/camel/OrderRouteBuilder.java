package com.example.camel;

import com.example.orders.OrderService;
import org.apache.camel.builder.RouteBuilder;

public class OrderRouteBuilder extends RouteBuilder {

    @Override
    public void configure() throws Exception {
        from("direct:enrich")
            .routeId("orders-enrich")
            .bean(OrderService.class, "enrich")
            .to("jms:queue:orders-out");
    }
}

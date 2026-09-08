# Enterprise-Java example — `orders` + `inventory`

A small **three-module** sample that exercises the v0.7.0 Java-framework graph:
Apache Camel routes (Java DSL **and** XML), in-process events, a Kafka
listener, a `@FeignClient` to a second service, an `@Aspect`, `@Transactional`,
and a MyBatis mapper. It complements [`../spring-boot/`](../spring-boot/) (the
v0.6.0 beans / MVC / Spring Data example).

```
enterprise-java-parent (pom)
├── orders-service
│   ├── OrderService        @Service @Transactional; publishes OrderPlacedEvent,
│   │                       KafkaTemplate.send("orders.outbound"), calls InventoryClient,
│   │                       enrich() ← invoked by the Camel route
│   ├── OrderPlacedEvent    in-process event
│   ├── OrderEventListener  @EventListener(OrderPlacedEvent) + @KafkaListener("orders.inbound")
│   ├── InventoryClient     @FeignClient(name="inventory", path="/inventory") GET /items/{sku}
│   ├── AuditAspect         @Aspect @Around execution(* …OrderService.*(..))
│   └── camel-context.xml   <route id="orders-xml-intake"> from jms:queue:orders
│                           → choice/when → to direct:enrich / direct:standard
├── camel-routes
│   └── OrderRouteBuilder   from("direct:enrich").bean(OrderService.class,"enrich")
│                                                .to("jms:queue:orders-out")
└── inventory-service
    ├── InventoryController @RestController @RequestMapping("/inventory") GET /items/{sku}
    │                       ← the FeignClient RESOLVES_TO this route
    ├── InventoryMapper     @Mapper interface
    └── mapper/InventoryMapper.xml  <select id="findBySku"> FROM inventory_items
```

## Ingest

```bash
grag-mcp apply-schema
grag-mcp ingest examples/enterprise-java
grag-mcp compute-centrality           # folds in the framework edges

# optional: compiler-grade call graph on top
grag-mcp scip-java examples/enterprise-java     # needs the scip-java binary + a build
```

## Query it (MCP)

| Ask | Tool call | Expect |
| --- | --- | --- |
| The whole shape | `get_architecture_outline()` | beans / endpoints / routes / listeners grouped by `orders-service` · `camel-routes` · `inventory-service` |
| Camel routes touching `direct:` | `get_routes(uri_glob="direct:*")` | `orders-xml-intake` (to `direct:enrich`) **and** `orders-enrich` (from `direct:enrich`) — paired through the shared `CamelEndpoint` |
| Who consumes the order event | `get_message_flows("OrderPlacedEvent")` | publisher `OrderService.place`, consumer `OrderEventListener.onOrderPlaced` |
| Who listens on `orders.inbound` | `get_message_flows("orders.inbound")` | consumer `OrderEventListener.consume`; producer side is `orders.outbound` |
| Cross-service call | `get_service_calls("com.example.orders.OrderService.place(String,String)")` | outbound `GET /inventory/items/{sku} → inventory`, `resolves_to_handler = InventoryController.getItem` |
| Bean context | `get_beans_for("com.example.orders.OrderService")` | `injects` the Feign client, `publishes OrderPlacedEvent`, `listens_to`/`calls_services` on its methods, `behaviors = [transactional]`, `invoked_by_routes = [orders-enrich]` |
| Everything transactional | `search_code("place order", behavior="transactional")` | `OrderService` |
| Code a route invokes | `search_code("enrich", route="orders-enrich")` | `OrderService.enrich` |
| Riskiest to change | `get_central_code_entities()` | `OrderService` ranks high — reached via the bean, the event, the route, and the Feign call |

The graph also carries `AuditAspect`'s `@Around` advice (`ADVISES` the
`OrderService` methods, best-effort) and the MyBatis `findBySku` statement
(`EXECUTES` → `ACCESSES {read}` → `DbTable "inventory_items"`).

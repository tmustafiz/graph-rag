# Enterprise-Java example — `orders`

A deliberately small **multi-module Spring Boot** app that exercises every
Java-framework feature the v0.6.0 graph models. Ingest it and query the Spring
model over MCP.

```
orders-parent (pom)
├── orders-domain
│   ├── Order            @Entity @Table(name="orders")  →  DbTable "orders" (if a schema is also ingested)
│   ├── OrderLine        @Entity @ManyToOne Order       →  RELATES_TO
│   ├── OrderStatus      enum, @Enumerated(STRING)
│   └── OrderRepository  extends JpaRepository<Order, Long>
│                        · findByCustomerIdAndStatusOrderByCreatedAtDesc  → derived (customerId, status)
│                        · withAtLeastLines   @Query                       → jpql
│                        · updateStatus       @Modifying @Query           → modifying
└── orders-api
    ├── OrdersApiApplication  @SpringBootApplication, @ImportResource(legacy-context.xml)
    ├── OrderController       @RestController @RequestMapping("/api/orders")  (GET /{id}, GET, POST)
    ├── OrderService          @Service, constructor-injects OrderRepository + OrderProperties,
    │                         field-injects NotificationGateway  (resolved to the XML bean)
    ├── OrderProperties       @ConfigurationProperties(prefix="orders")   → BINDS application.yml
    ├── EmailNotificationGateway   plain class — a bean only via XML
    ├── application.yml
    └── legacy-context.xml    <bean id="notificationGateway" class="…EmailNotificationGateway">
                              <context:property-placeholder location="classpath:application.yml"/>
```

## Ingest

```bash
grag-mcp apply-schema
grag-mcp ingest examples/spring-boot
grag-mcp compute-centrality        # optional, for get_central_code_entities
```

A directory ingest runs the four post-ingest passes (`ProjectModelResolver`,
`SpringBeanResolver`, `SpringXmlResolver`, `SpringDataResolver`) automatically.

## Query (MCP tools, or the equivalent Cypher)

**Controllers in a module**

```
search_code(query="order controller", stereotype="RestController", module="orders-api")
```

**A bean's wiring**

```
get_beans_for("com.example.orders.api.OrderService")
# → stereotype "Service";
#   injects: orderRepository (constructor), orderProperties (constructor),
#            notificationGateway (field)   ← the XML-wired bean
#   binds:   —   (OrderProperties holds the @ConfigurationProperties bind)
```

```
get_beans_for("com.example.orders.api.OrderProperties")
# → binds: orders.notify-on-create, orders.max-lines-per-order
```

**HTTP routes**

```
get_endpoints(path_glob="/api/orders*")
# → GET  /api/orders/{id}   OrderController.getOrder    [spring-mvc]
#   GET  /api/orders        OrderController.listOrders  [spring-mvc]
#   POST /api/orders        OrderController.createOrder [spring-mvc]
```

**Repository → entity → relations**

```
get_neighbors("com.example.orders.domain.OrderRepository", rel_types=["MANAGES"])
#   → com.example.orders.domain.Order   (:JpaEntity)
get_neighbors("com.example.orders.domain.Order", rel_types=["RELATES_TO", "PERSISTS_AS"])
#   → OrderLine  (RELATES_TO {kind:"one-to-many", mapped_by:"order"})
search_code(query="repository", stereotype="Repository")
#   → OrderRepository;  its methods carry query_kind / query_text / query_properties
```

**Config**

```
search(query="datasource url", source_type="config")
get_neighbors("com.example.orders.api.OrderProperties", rel_types=["BINDS"])
```

## Limitations

Java resolution is best-effort static — no type inference, no library symbols.
`Order → orders` `PERSISTS_AS` only links if a SQL schema defining a table
named `orders` is also ingested. Precise cross-file / library-level resolution
is the v0.7.0 `--scip` path.

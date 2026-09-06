-- grag:dialect=postgres
-- Core order-taking schema: regions, customers, orders.

CREATE TABLE sales.region (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    is_active   BOOLEAN DEFAULT TRUE
);

CREATE TABLE sales.customer (
    id          INTEGER PRIMARY KEY,
    email       VARCHAR(255) NOT NULL,
    region_id   INTEGER REFERENCES sales.region (id),
    created_at  TIMESTAMP DEFAULT now()
);

CREATE TABLE sales.orders (
    id           BIGINT PRIMARY KEY,
    customer_id  INTEGER NOT NULL,
    lane         TEXT DEFAULT 'standard',
    total        NUMERIC(10, 2) DEFAULT 0,
    placed_at    TIMESTAMP DEFAULT now(),
    CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id) REFERENCES sales.customer (id)
);

CREATE INDEX idx_orders_customer ON sales.orders (customer_id);
CREATE UNIQUE INDEX idx_customer_email ON sales.customer (email);

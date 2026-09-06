-- grag:dialect=postgres
-- Reporting layer: a line-item table that back-references orders, plus a view.

CREATE TABLE sales.order_line (
    id          BIGINT PRIMARY KEY,
    order_id    BIGINT NOT NULL REFERENCES sales.orders (id),
    sku         TEXT NOT NULL,
    quantity    INTEGER DEFAULT 1,
    unit_price  NUMERIC(10, 2) NOT NULL
);

-- A back-fill constraint added after the fact, the way a later migration would.
ALTER TABLE sales.orders
    ADD CONSTRAINT fk_orders_region FOREIGN KEY (customer_id) REFERENCES sales.region (id);

CREATE VIEW sales.v_expedited_orders AS
    SELECT o.id,
           c.email,
           o.total
      FROM sales.orders o
      JOIN sales.customer c ON c.id = o.customer_id
     WHERE o.lane = 'expedited';

-- grag:dialect=oracle
-- Order operations: submit / expedite / publish, plus an audit trigger.
-- Reads and writes the tables defined in ../001_core.sql.

CREATE OR REPLACE PACKAGE sales.order_ops AS
    PROCEDURE submit(p_id IN NUMBER);
    PROCEDURE expedite(p_id IN NUMBER);
    FUNCTION open_count RETURN NUMBER;
END order_ops;
/

CREATE OR REPLACE PACKAGE BODY sales.order_ops AS

    PROCEDURE publish(p_id IN NUMBER) IS
    BEGIN
        INSERT INTO sales.order_line (id, order_id, sku, unit_price)
        VALUES (p_id, p_id, 'PUBLISH', 0);
    END publish;

    PROCEDURE submit(p_id IN NUMBER) IS
    BEGIN
        UPDATE sales.orders SET lane = 'standard' WHERE id = p_id;
        publish(p_id);
    END submit;

    PROCEDURE expedite(p_id IN NUMBER) IS
    BEGIN
        UPDATE sales.orders SET lane = 'expedited' WHERE id = p_id;
        publish(p_id);
    END expedite;

    FUNCTION open_count RETURN NUMBER IS
        n NUMBER;
    BEGIN
        SELECT COUNT(*) INTO n FROM sales.orders WHERE lane <> 'closed';
        RETURN n;
    END open_count;

END order_ops;
/

CREATE OR REPLACE TRIGGER sales.trg_order_line_audit
AFTER INSERT ON sales.order_line
FOR EACH ROW
BEGIN
    UPDATE sales.orders SET total = total + :new.unit_price WHERE id = :new.order_id;
END;
/

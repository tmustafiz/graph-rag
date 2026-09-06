import { Order } from "../model/order";

/** Small coloured badge showing an order's routing lane. */
export function OrderBadge({ order, onClick }: { order: Order; onClick: () => void }) {
  const label = order.priority ? "priority" : "standard";
  return (
    <button className={`lane-${label}`} onClick={onClick}>
      {label}
    </button>
  );
}

/** A row of badges — renders one `<OrderBadge>` per order. */
export function OrderBadgeList({ orders }: { orders: Order[] }) {
  return (
    <div className="badge-list">
      {orders.map((order) => (
        <OrderBadge key={order.id} order={order} onClick={() => undefined} />
      ))}
    </div>
  );
}

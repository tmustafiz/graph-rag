/** A single customer order. */
export interface Order {
  id: string;
  quantity: number;
  priority: boolean;
}

/** How an order may be routed through the warehouse. */
export type Lane = "standard" | "priority";

/** True when this order should jump the queue. */
export function isExpedited(order: Order): boolean {
  return order.priority || order.quantity > 100;
}

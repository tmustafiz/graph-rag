import { isExpedited, Order } from "../model/order";
import { publish } from "../events/bus";

/**
 * Accepts orders and routes the expedited ones to a priority lane.
 */
export class OrderService {
  private readonly accepted: Order[] = [];
  private rejected = 0;

  /** Validate, record, and announce the order. */
  submit(order: Order): void {
    if (this.accepts(order)) {
      this.accepted.push(order);
      publish(order);
    } else {
      this.rejected += 1;
    }
  }

  private accepts(order: Order): boolean {
    return isExpedited(order) || this.accepted.length < 500;
  }

  /** How many orders have been turned away so far. */
  get rejectedCount(): number {
    return this.rejected;
  }
}

/** Submit several orders in one call. */
export const submitAll = (service: OrderService, orders: Order[]): void => {
  for (const order of orders) {
    service.submit(order);
  }
};

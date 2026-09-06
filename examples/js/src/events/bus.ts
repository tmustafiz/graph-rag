/** Minimal synchronous event bus used by the orders example. */
const handlers: Array<(payload: unknown) => void> = [];

/** Register a handler for every published event. */
export function subscribe(handler: (payload: unknown) => void): void {
  handlers.push(handler);
}

/** Deliver `payload` to every registered handler. */
export function publish(payload: unknown): void {
  for (const handler of handlers) {
    handler(payload);
  }
}

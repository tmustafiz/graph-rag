# Orchard Task Queue

Orchard is a small fictional task queue used only as fixture content for the
retrieval regression eval. Nothing here describes a real product.

## Concepts and terminology

An Orchard deployment has three moving parts. A **producer** submits tasks. A
**queue** holds pending tasks in priority order. A **worker** leases a task,
runs it, and acknowledges completion. A task that is leased but never
acknowledged is **reclaimed** after its visibility timeout and made available to
another worker. Understanding the producer / queue / worker split, and the
lease-then-acknowledge lifecycle, is enough to follow the rest of this guide.

## Creating a queue

Create a queue with the admin CLI:

```
orchard queue create --name builds --priority-levels 3
```

The name must be unique within the deployment. `--priority-levels` fixes how
many distinct priorities the queue accepts; it cannot be changed after
creation. A newly created queue is empty and immediately accepts submissions.

### Retry and backoff

When a worker reports a task as failed, or the task is reclaimed after its
visibility timeout, Orchard re-enqueues it and increments its attempt counter.
Re-enqueued tasks are delayed by exponential backoff: the delay is
`base_delay * 2 ** (attempts - 1)`, capped at `max_delay`. Once a task reaches
`max_attempts` it is moved to the dead-letter queue instead of being retried
again. `base_delay`, `max_delay`, and `max_attempts` are per-queue settings.

## Encryption in transit

All traffic between producers, workers, and the Orchard broker is encrypted in
transit with TLS 1.3. The broker presents a certificate that clients verify
against a configured CA bundle; connections that fail verification are dropped
before any task data is exchanged. There is no option to disable TLS, even for
same-host connections.

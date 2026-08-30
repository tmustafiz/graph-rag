# Deploying Orchard

Fixture content for the retrieval regression eval. Orchard is not a real
product; these instructions do not run anything.

## Prerequisites

A deployment needs a POSIX host with at least 2 CPUs and 4 GB of RAM, outbound
network access to the broker, and a writable data directory for the queue log.
The admin CLI (`orchard`) must be on `PATH`. No database is required — the queue
log is a single append-only file per queue.

## Running locally

Start a single-node broker for development:

```
orchard broker start --data-dir ./orchard-data
```

The broker listens on port 7000 by default. A local broker keeps everything in
one process and is not suitable for production, where producers, the broker, and
workers run on separate hosts.

## Configuration reference

Configuration is read once at broker startup. Changing a setting requires a
restart; there is no live reload.

### Environment variables

The broker is configured entirely through environment variables:

- `ORCHARD_DATA_DIR` — directory for the append-only queue logs. Required.
- `ORCHARD_LISTEN_ADDR` — host:port the broker binds to. Default `0.0.0.0:7000`.
- `ORCHARD_CA_BUNDLE` — path to the CA bundle workers and producers are verified
  against. Required when `ORCHARD_REQUIRE_MTLS` is set.
- `ORCHARD_REQUIRE_MTLS` — when `true`, clients must present a certificate the
  broker can verify. Default `false`.
- `ORCHARD_LOG_LEVEL` — one of `debug`, `info`, `warn`, `error`. Default `info`.

## Health checks

The broker exposes `GET /healthz` on its listen address. It returns `200` once
the queue logs are open and the broker is accepting connections, and `503`
during startup or shutdown. Orchestrators should treat a `503` as "not ready
yet" rather than "failed".

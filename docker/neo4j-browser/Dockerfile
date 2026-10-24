# syntax=docker/dockerfile:1

# Neo4j Browser served as plain static files, extracted from a stock Neo4j
# image. Opt-in sidecar for when the main NEO4J_IMAGE is a hardened build that
# ships without the Browser web UI (e.g. dhi.io/neo4j:2026). Only built/run
# when you pass `docker compose --profile browser`.
ARG NEO4J_BROWSER_SOURCE_IMAGE=neo4j:2026.07.1

FROM ${NEO4J_BROWSER_SOURCE_IMAGE} AS src
WORKDIR /tmp/nb
# The stock image keeps the Browser bundle as a zip under web/; the JDK's jar
# tool is already on PATH. Extraction yields ./browser/index.html + assets.
RUN /opt/java/openjdk/bin/jar xf "$(ls /var/lib/neo4j/web/neo4j-browser-*.zip)"

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY --from=src /tmp/nb/browser /usr/share/nginx/html/browser
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080

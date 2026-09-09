"""Declarative HTTP clients: `HttpEndpointExtractor` outbound endpoints for
`@FeignClient` / `@HttpExchange` interfaces, plus `ServiceCallResolver._assemble`
(pure — no Neo4j).
"""

from pathlib import Path

from graph_rag.graph.service_call_resolver import ServiceCallResolver
from graph_rag.ingest.parsers.java_parser import JavaParser

_FEIGN = """\
package com.acme.orders.client;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.*;

@FeignClient(name = "inventory", path = "/inventory")
public interface InventoryClient {

    @GetMapping("/items/{sku}")
    Item getItem(@PathVariable String sku);

    @PostMapping("/reservations")
    Reservation reserve(@RequestBody ReserveRequest body);
}
"""

_HTTP_EXCHANGE = """\
package com.acme.orders.client;

import org.springframework.web.service.annotation.*;

@HttpExchange("/pricing")
public interface PricingClient {

    @GetExchange("/quote/{sku}")
    Quote quote(@PathVariable String sku);
}
"""


def _endpoints(tmp_path: Path, name: str, body: str):
    package_dir = tmp_path / "com" / "acme" / "orders" / "client"
    package_dir.mkdir(parents=True, exist_ok=True)
    path = package_dir / name
    path.write_text(body)
    return {
        (endpoint.http_method, endpoint.path): endpoint
        for endpoint in JavaParser().parse(path).http_endpoints
    }


def test_feign_client_composes_base_and_method_paths(tmp_path: Path) -> None:
    endpoints = _endpoints(tmp_path, "InventoryClient.java", _FEIGN)

    get = endpoints[("GET", "/inventory/items/{sku}")]
    assert get.outbound is True
    assert get.framework == "feign"
    assert get.target_service == "inventory"
    assert get.handler_qualified_name == ("com.acme.orders.client.InventoryClient.getItem(String)")
    assert ("POST", "/inventory/reservations") in endpoints


def test_http_exchange_interface_client(tmp_path: Path) -> None:
    endpoints = _endpoints(tmp_path, "PricingClient.java", _HTTP_EXCHANGE)

    quote = endpoints[("GET", "/pricing/quote/{sku}")]
    assert quote.outbound is True
    assert quote.framework == "spring-http-interface"


_HTTP_EXCHANGE_URL = """\
package com.acme.orders.client;

import org.springframework.web.service.annotation.*;

@HttpExchange(url = "/api/persons")
public interface PersonClient {

    @GetExchange(url = "/{id}")
    Person get(@PathVariable String id);

    @PostExchange(url = "/")
    Person create(@RequestBody Person body);
}
"""


def test_http_exchange_url_attribute_supplies_base_and_method_paths(tmp_path: Path) -> None:
    """#165.5 — `@HttpExchange(url=)` / `@GetExchange(url=)` must not drop the path."""
    endpoints = _endpoints(tmp_path, "PersonClient.java", _HTTP_EXCHANGE_URL)

    assert ("GET", "/api/persons/{id}") in endpoints
    assert ("POST", "/api/persons") in endpoints
    assert endpoints[("GET", "/api/persons/{id}")].target_service == "/api/persons"


# -- ServiceCallResolver._assemble --


def _out(endpoint_id, method, path):
    return {"id": endpoint_id, "method": method, "path": path}


def test_outbound_resolves_to_the_matching_inbound_route() -> None:
    outbound = [_out("o1", "GET", "/inventory/items/{sku}")]
    inbound = [
        _out("i1", "GET", "/inventory/items/{id}"),
        _out("i2", "POST", "/inventory/reservations"),
    ]

    assembled = ServiceCallResolver._assemble(outbound, inbound)

    assert assembled.resolves_to == [{"from": "o1", "to": "i1"}]


def test_unmatched_outbound_is_left_standalone() -> None:
    outbound = [_out("o1", "GET", "/external/thing")]
    inbound = [_out("i1", "GET", "/inventory/items/{id}")]

    assembled = ServiceCallResolver._assemble(outbound, inbound)

    assert assembled.resolves_to == []


def test_ambiguous_inbound_match_is_not_linked() -> None:
    outbound = [_out("o1", "*", "/inventory/items/{sku}")]
    inbound = [
        _out("i1", "GET", "/inventory/items/{id}"),
        _out("i2", "PUT", "/inventory/items/{id}"),
    ]

    assembled = ServiceCallResolver._assemble(outbound, inbound)

    assert assembled.resolves_to == []

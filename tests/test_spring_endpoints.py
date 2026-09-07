from pathlib import Path

from graph_rag.ingest.parsers import JavaParser

_SPRING_CONTROLLER = """\
package com.acme.web;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/orders")
public class OrderController {

    @GetMapping("/{id}")
    public Order getOrder(@PathVariable Long id, @RequestParam(required = false) String expand) {
        return null;
    }

    @PostMapping(value = "", consumes = "application/json", produces = "application/json")
    public Order create(@RequestBody CreateOrderRequest body) {
        return null;
    }

    @PutMapping("/{id}")
    public void replace(@PathVariable Long id, @RequestBody Order order) {}

    @DeleteMapping("/{id}")
    public void remove(@PathVariable Long id) {}

    @PatchMapping("/{id}")
    public void patch(@PathVariable Long id) {}

    @RequestMapping(path = "/search", method = {RequestMethod.GET, RequestMethod.POST})
    public java.util.List<Order> search() {
        return null;
    }
}
"""

_JAXRS_RESOURCE = """\
package com.acme.jax;

import javax.ws.rs.*;

@Path("/ping")
public class PingResource {

    @GET
    @Produces("text/plain")
    public String ping(@QueryParam("name") String name) {
        return "pong";
    }

    @POST
    @Path("/echo")
    @Consumes("application/json")
    public Message echo(Message message) {
        return message;
    }
}
"""


def _endpoints(tmp_path: Path, name: str, body: str):
    path = tmp_path / name
    path.write_text(body)
    return {
        (endpoint.http_method, endpoint.path): endpoint
        for endpoint in JavaParser().parse(path).http_endpoints
    }


def test_class_and_method_paths_compose(tmp_path: Path) -> None:
    endpoints = _endpoints(tmp_path, "OrderController.java", _SPRING_CONTROLLER)

    assert ("GET", "/api/orders/{id}") in endpoints
    assert ("POST", "/api/orders") in endpoints  # method path was ""
    assert ("GET", "/api/orders/search") in endpoints
    assert ("POST", "/api/orders/search") in endpoints  # RequestMapping method list


def test_every_http_method_shortcut_is_recognised(tmp_path: Path) -> None:
    endpoints = _endpoints(tmp_path, "OrderController.java", _SPRING_CONTROLLER)

    methods_for_id = {method for (method, path) in endpoints if path == "/api/orders/{id}"}
    assert methods_for_id == {"GET", "PUT", "DELETE", "PATCH"}


def test_produces_consumes_and_request_body_binding(tmp_path: Path) -> None:
    endpoints = _endpoints(tmp_path, "OrderController.java", _SPRING_CONTROLLER)

    create = endpoints[("POST", "/api/orders")]
    assert create.produces == ["application/json"]
    assert create.consumes == ["application/json"]
    assert create.framework == "spring-mvc"
    assert {"kind": "body", "name": "body", "param_type": "CreateOrderRequest"} in create.bindings

    get = endpoints[("GET", "/api/orders/{id}")]
    kinds = {(b["kind"], b["name"], b["param_type"]) for b in get.bindings}
    assert kinds == {("path", "id", "Long"), ("query", "expand", "String")}


def test_embed_text_is_natural_language(tmp_path: Path) -> None:
    endpoints = _endpoints(tmp_path, "OrderController.java", _SPRING_CONTROLLER)

    assert (
        endpoints[("GET", "/api/orders/{id}")].embed_text
        == "GET /api/orders/{id} -> OrderController.getOrder (returns Order) [spring-mvc]"
    )


def test_jax_rs_endpoints(tmp_path: Path) -> None:
    endpoints = _endpoints(tmp_path, "PingResource.java", _JAXRS_RESOURCE)

    ping = endpoints[("GET", "/ping")]
    assert ping.framework == "jax-rs"
    assert ping.produces == ["text/plain"]
    assert {"kind": "query", "name": "name", "param_type": "String"} in ping.bindings

    echo = endpoints[("POST", "/ping/echo")]
    assert echo.consumes == ["application/json"]


def test_exception_handler_recorded_best_effort(tmp_path: Path) -> None:
    endpoints = _endpoints(
        tmp_path,
        "Advice.java",
        "package com.acme.web;\n"
        "import org.springframework.web.bind.annotation.*;\n"
        "@RestControllerAdvice\n"
        "public class Advice {\n"
        "  @ExceptionHandler(OrderNotFound.class)\n"
        "  public ErrorBody handle(OrderNotFound ex) { return null; }\n"
        "}",
    )

    assert ("EXCEPTION", "OrderNotFound") in endpoints


def test_graph_writer_serialises_endpoint_rows_with_bindings_json(tmp_path: Path) -> None:
    path = tmp_path / "OrderController.java"
    path.write_text(_SPRING_CONTROLLER)
    document = JavaParser().parse(path)

    row = document.http_endpoints[0].model_dump(mode="json")
    assert isinstance(row["bindings_json"], str)
    assert row["id"] and row["handler_qualified_name"].startswith("com.acme.web.OrderController.")

import re
from typing import Any

from ..models import Annotation, CodeEntity, HttpEndpoint

# method-level Spring mapping annotation → HTTP method it implies.
_SPRING_METHOD_MAPPINGS = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
}
_JAX_RS_METHODS = {"GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"}
# Spring 6 HTTP-interface (`@HttpExchange`) shortcut → HTTP method.
_EXCHANGE_METHOD_MAPPINGS = {
    "GetExchange": "GET",
    "PostExchange": "POST",
    "PutExchange": "PUT",
    "DeleteExchange": "DELETE",
    "PatchExchange": "PATCH",
}
_JAX_RS_PARAM_BINDINGS = {
    "PathParam": "path",
    "QueryParam": "query",
    "HeaderParam": "header",
    "FormParam": "form",
}
_SPRING_PARAM_BINDINGS = {
    "PathVariable": "path",
    "RequestParam": "query",
    "RequestBody": "body",
    "RequestHeader": "header",
    "ModelAttribute": "model",
}
_PARAM_BINDINGS = {**_JAX_RS_PARAM_BINDINGS, **_SPRING_PARAM_BINDINGS}
_MODIFIERS = {
    "public",
    "private",
    "protected",
    "static",
    "final",
    "abstract",
    "synchronized",
    "native",
    "default",
}

# A Java single- or double-quoted literal (with `\`-escapes). Blanked out before
# the signature is scanned for brackets, so a `)` / `,` / `<` inside an
# annotation attribute value (`@Pattern(regexp = ")")`) can't unbalance the
# depth counters.
_STRING_LITERAL = re.compile(r'"(?:\\.|[^"\\])*"' + r"|'(?:\\.|[^'\\])*'")


class HttpEndpointExtractor:
    """Derives `HttpEndpoint`s from a parsed `.java` file's `CodeEntity` +
    `Annotation` lists — a controller and its handlers always live in one file,
    so this needs no cross-file resolution.

    Spring MVC (`@RequestMapping` + `@GetMapping` / `@PostMapping` / …, class +
    method path composition, `produces` / `consumes` / `params` / `headers`)
    and JAX-RS (`@Path` + `@GET` / `@POST` / …, `@Produces` / `@Consumes`).
    Parameter bindings (`@PathVariable`, `@RequestParam`, `@RequestBody`, … /
    `@PathParam`, `@QueryParam`, …) are matched to the handler's parameters by
    name, their types read from the method signature. `@ExceptionHandler`
    methods are recorded best-effort with `http_method="EXCEPTION"`.
    """

    @classmethod
    def extract(
        cls, entities: list[CodeEntity], annotations: list[Annotation]
    ) -> list[HttpEndpoint]:
        by_owner: dict[str, list[Annotation]] = {}
        for annotation in annotations:
            by_owner.setdefault(annotation.owner_qualified_name, []).append(annotation)

        methods_by_type: dict[str, list[CodeEntity]] = {}
        types: dict[str, CodeEntity] = {}
        for entity in entities:
            if entity.kind == "method" and entity.parent_qualified_name:
                methods_by_type.setdefault(entity.parent_qualified_name, []).append(entity)
            elif entity.kind in ("class", "interface"):
                types[entity.qualified_name] = entity

        endpoints: list[HttpEndpoint] = []
        for type_qn, type_entity in types.items():
            type_annos = by_owner.get(type_qn, [])
            client = cls._client_spec(type_annos, methods_by_type.get(type_qn, []), by_owner)
            if client is not None:
                for method in methods_by_type.get(type_qn, []):
                    method_annos = by_owner.get(method.qualified_name, [])
                    endpoints.extend(
                        cls._client_endpoints_for_method(
                            method, method_annos, type_entity.name, client
                        )
                    )
                continue
            class_paths = cls._all_paths(type_annos, ("RequestMapping", "Path"))
            class_produces = cls._media(type_annos, "produces", "Produces")
            class_consumes = cls._media(type_annos, "consumes", "Consumes")
            for method in methods_by_type.get(type_qn, []):
                method_annos = by_owner.get(method.qualified_name, [])
                param_annos = [a for a in method_annos if a.target.startswith("param:")]
                method_only = [a for a in method_annos if a.target == "method"]
                endpoints.extend(
                    cls._endpoints_for_method(
                        method,
                        method_only,
                        param_annos,
                        type_entity.name,
                        class_paths,
                        class_produces,
                        class_consumes,
                    )
                )
        return endpoints

    # -- per-method --

    @classmethod
    def _endpoints_for_method(
        cls,
        method: CodeEntity,
        method_annos: list[Annotation],
        param_annos: list[Annotation],
        controller_name: str,
        class_paths: list[str],
        class_produces: list[str],
        class_consumes: list[str],
    ) -> list[HttpEndpoint]:
        names = {annotation.name for annotation in method_annos}
        framework = (
            "spring-mvc"
            if names & ({"RequestMapping", *_SPRING_METHOD_MAPPINGS} | {"ExceptionHandler"})
            else "jax-rs"
            if names & (_JAX_RS_METHODS | {"Path"})
            else None
        )
        if framework is None:
            return []

        param_types = cls._signature_params(method.signature, method.name)
        bindings = cls._bindings(param_annos, param_types)
        return_type = cls._return_type(method.signature, method.name)

        if "ExceptionHandler" in names:
            handled = [
                exc.removesuffix(".class")
                for exc in cls._string_list(cls._attr(method_annos, "ExceptionHandler", "value"))
            ]
            return [
                cls._build(
                    method,
                    "EXCEPTION",
                    exc or "*",
                    "spring-mvc",
                    [],
                    [],
                    [],
                    bindings,
                    controller_name,
                    return_type,
                )
                for exc in (handled or ["*"])
            ]

        http_methods = cls._http_methods(method_annos, framework)
        method_paths = cls._all_paths(
            method_annos, ("RequestMapping", *_SPRING_METHOD_MAPPINGS, "Path")
        )
        paths = _dedupe(
            cls._join(class_path, method_path)
            for class_path in class_paths
            for method_path in method_paths
        )
        produces = cls._media(method_annos, "produces", "Produces") or class_produces
        consumes = cls._media(method_annos, "consumes", "Consumes") or class_consumes
        params = cls._string_list(cls._attr(method_annos, "RequestMapping", "params"))
        params += cls._string_list(cls._attr(method_annos, "RequestMapping", "headers"))

        return [
            cls._build(
                method,
                http_method,
                path,
                framework,
                produces,
                consumes,
                params,
                bindings,
                controller_name,
                return_type,
            )
            for http_method in http_methods
            for path in paths
        ]

    @classmethod
    def _build(
        cls,
        method: CodeEntity,
        http_method: str,
        path: str,
        framework: str,
        produces: list[str],
        consumes: list[str],
        params: list[str],
        bindings: list[dict[str, Any]],
        controller_name: str,
        return_type: str | None,
        *,
        outbound: bool = False,
        target_service: str | None = None,
    ) -> HttpEndpoint:
        if outbound:
            caller = f"{controller_name}.{method.name}"
            summary = f"{http_method} {path} -> {target_service or '?'} (client {caller})"
        else:
            summary = f"{http_method} {path} -> {controller_name}.{method.name}"
        if return_type and return_type not in ("void", "?"):
            summary += f" (returns {return_type})"
        summary += f" [{'outbound ' if outbound else ''}{framework}]"
        return HttpEndpoint(
            handler_qualified_name=method.qualified_name,
            http_method=http_method,
            path=path,
            framework=framework,
            produces=produces,
            consumes=consumes,
            params=params,
            bindings=bindings,
            outbound=outbound,
            target_service=target_service,
            embed_text=summary,
        )

    # -- declarative HTTP clients (@FeignClient / @HttpExchange) --

    @classmethod
    def _client_spec(
        cls,
        type_annos: list[Annotation],
        methods: list[CodeEntity],
        by_owner: dict[str, list[Annotation]],
    ) -> dict[str, Any] | None:
        """`None` for a normal controller; otherwise
        `{framework, target_service, base_paths}` for a `@FeignClient` /
        `@HttpExchange` interface client (or a plain interface whose methods
        carry `@GetExchange` / … shortcuts).
        """
        for annotation in type_annos:
            if annotation.name == "FeignClient":
                service = (
                    annotation.attributes.get("value")
                    or annotation.attributes.get("name")
                    or annotation.attributes.get("url")
                )
                base_paths = cls._string_list(annotation.attributes.get("path")) or [""]
                return {
                    "framework": "feign",
                    "target_service": str(service) if service else None,
                    "base_paths": base_paths,
                }
            if annotation.name == "HttpExchange":
                return {
                    "framework": "spring-http-interface",
                    # `@HttpExchange` uses `url` and `value` as aliases for the
                    # base URI — accept either.
                    "target_service": annotation.attributes.get("url")
                    or annotation.attributes.get("value"),
                    "base_paths": cls._all_paths([annotation], ("HttpExchange",)),
                }
        has_exchange_method = any(
            anno.name in _EXCHANGE_METHOD_MAPPINGS or anno.name == "HttpExchange"
            for method in methods
            for anno in by_owner.get(method.qualified_name, [])
        )
        if has_exchange_method:
            return {
                "framework": "spring-http-interface",
                "target_service": None,
                "base_paths": [""],
            }
        return None

    @classmethod
    def _client_endpoints_for_method(
        cls,
        method: CodeEntity,
        method_annos: list[Annotation],
        client_name: str,
        client: dict[str, Any],
    ) -> list[HttpEndpoint]:
        method_only = [a for a in method_annos if a.target == "method"]
        param_annos = [a for a in method_annos if a.target.startswith("param:")]
        names = {a.name for a in method_only}

        if client["framework"] == "feign":
            if not (names & ({"RequestMapping", *_SPRING_METHOD_MAPPINGS})):
                return []
            http_methods = cls._http_methods(method_only, "spring-mvc")
            method_paths = cls._all_paths(method_only, ("RequestMapping", *_SPRING_METHOD_MAPPINGS))
        else:
            exchange = names & set(_EXCHANGE_METHOD_MAPPINGS)
            if exchange:
                http_methods = [_EXCHANGE_METHOD_MAPPINGS[name] for name in exchange]
                method_paths = cls._all_paths(
                    method_only, (*_EXCHANGE_METHOD_MAPPINGS, "HttpExchange")
                )
            elif "HttpExchange" in names:
                raw = cls._attr(method_only, "HttpExchange", "method")
                http_methods = [v.rsplit(".", 1)[-1] for v in cls._string_list(raw)] or ["*"]
                method_paths = cls._all_paths(method_only, ("HttpExchange",))
            else:
                return []

        paths = _dedupe(
            cls._join(base_path, method_path)
            for base_path in client["base_paths"]
            for method_path in method_paths
        )
        param_types = cls._signature_params(method.signature, method.name)
        bindings = cls._bindings(param_annos, param_types)
        return_type = cls._return_type(method.signature, method.name)
        return [
            cls._build(
                method,
                http_method,
                path,
                client["framework"],
                [],
                [],
                [],
                bindings,
                client_name,
                return_type,
                outbound=True,
                target_service=client["target_service"],
            )
            for http_method in http_methods
            for path in paths
        ]

    # -- annotation attribute helpers --

    @classmethod
    def _http_methods(cls, method_annos: list[Annotation], framework: str) -> list[str]:
        if framework == "jax-rs":
            found = [a.name for a in method_annos if a.name in _JAX_RS_METHODS]
            return found or ["*"]
        for annotation in method_annos:
            if annotation.name in _SPRING_METHOD_MAPPINGS:
                return [_SPRING_METHOD_MAPPINGS[annotation.name]]
        raw = cls._attr(method_annos, "RequestMapping", "method")
        verbs = [value.rsplit(".", 1)[-1] for value in cls._string_list(raw)]
        return verbs or ["*"]

    @classmethod
    def _all_paths(cls, annos: list[Annotation], anno_names: tuple[str, ...]) -> list[str]:
        """Every path a `@RequestMapping` / `@GetMapping` / `@Path` declares —
        `@GetMapping({"/a", "/b"})` maps to two routes, not one. `[""]` when the
        annotation carries no path, so the class×method cartesian product still
        runs once. `@HttpExchange` / `@GetExchange` name their sub-path `url`.
        """
        paths: list[str] = []
        for annotation in annos:
            if annotation.name not in anno_names:
                continue
            for key in ("value", "path", "url"):
                raw = annotation.attributes.get(key)
                if raw is None:
                    continue
                # keep "" — `@GetMapping({"", "/list"})` maps the base path too
                items = raw if isinstance(raw, (list, tuple)) else [raw]
                paths.extend(str(item) for item in items)
        return _dedupe(paths) or [""]

    @classmethod
    def _media(cls, annos: list[Annotation], spring_attr: str, jaxrs_anno: str) -> list[str]:
        for annotation in annos:
            if annotation.name in ("RequestMapping", *_SPRING_METHOD_MAPPINGS):
                values = cls._string_list(annotation.attributes.get(spring_attr))
                if values:
                    return values
            if annotation.name == jaxrs_anno:
                values = cls._string_list(annotation.attributes.get("value"))
                if values:
                    return values
        return []

    @staticmethod
    def _attr(annos: list[Annotation], anno_name: str, attr: str) -> Any:
        for annotation in annos:
            if annotation.name == anno_name and attr in annotation.attributes:
                return annotation.attributes[attr]
        return None

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value else []
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value if item != ""]
        return [str(value)]

    # -- parameter bindings --

    @classmethod
    def _bindings(
        cls, param_annos: list[Annotation], param_types: dict[str, str]
    ) -> list[dict[str, Any]]:
        bindings: list[dict[str, Any]] = []
        for annotation in param_annos:
            kind = _PARAM_BINDINGS.get(annotation.name)
            if kind is None:
                continue
            param_name = annotation.target.split(":", 1)[1]
            explicit = cls._string_list(annotation.attributes.get("value"))
            bindings.append(
                {
                    "kind": kind,
                    "name": explicit[0] if explicit else param_name,
                    "param_type": param_types.get(param_name, "?"),
                }
            )
        return bindings

    @staticmethod
    def _signature_params(signature: str | None, method_name: str) -> dict[str, str]:
        if not signature:
            return {}
        signature = _STRING_LITERAL.sub('""', signature)
        match = re.search(rf"\b{re.escape(method_name)}\s*\(", signature)
        if match is None:
            return {}
        depth = 0
        chunk = ""
        for char in signature[match.end() - 1 :]:
            if char in "([<":
                depth += 1
                if char == "(" and depth == 1:
                    continue
            elif char in ")]>":
                depth -= 1
                if depth == 0:
                    break
            chunk += char
        params: dict[str, str] = {}
        for raw in _split_top_level(chunk):
            cleaned = re.sub(r"@\w+(\([^)]*\))?\s*", "", raw).strip()
            tokens = cleaned.split()
            if len(tokens) >= 2:
                params[tokens[-1]] = " ".join(tokens[:-1])
        return params

    @staticmethod
    def _return_type(signature: str | None, method_name: str) -> str | None:
        if not signature:
            return None
        match = re.search(rf"([\w.$<>, \[\]]+?)\s+{re.escape(method_name)}\s*\(", signature)
        if match is None:
            return None
        tokens = [t for t in match.group(1).split() if t not in _MODIFIERS]
        return tokens[-1] if tokens else None

    @staticmethod
    def _join(prefix: str, suffix: str) -> str:
        parts = [segment.strip("/") for segment in (prefix, suffix) if segment.strip("/")]
        return "/" + "/".join(parts) if parts else "/"


def _dedupe(items: Any) -> list[str]:
    """Order-preserving de-dup — a class- and method-level path that compose to
    the same route, or a repeated array entry, collapse to one endpoint."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _split_top_level(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current = ""
    for char in text:
        if char in "([<":
            depth += 1
        elif char in ")]>":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    if current.strip():
        parts.append(current)
    return parts

"""AOP & behavioral-annotation model: `AopExtractor` over a parsed `.java`
file, plus `AopResolver._assemble` (pure — no Neo4j).
"""

from pathlib import Path

from graph_rag.graph.aop_resolver import AopResolver
from graph_rag.ingest.parsers.java_parser import JavaParser

_ASPECT = """\
package com.acme.aop;

import org.aspectj.lang.annotation.*;

@Aspect
public class AuditAspect {

    @Pointcut("execution(* com.acme.service..*(..))")
    public void serviceMethods() {}

    @Around("serviceMethods()")
    public Object audit(ProceedingJoinPoint pjp) throws Throwable {
        return pjp.proceed();
    }

    @Before("execution(* com.acme.web.*Controller.*(..))")
    public void logEntry() {}

    @After("execution(* com.acme.missing..*(..))")
    public void never() {}
}
"""

_BEHAVIOR = """\
package com.acme.service;

import org.springframework.transaction.annotation.*;
import org.springframework.scheduling.annotation.*;

@Transactional(readOnly = true)
public class OrderService {

    @Transactional(propagation = Propagation.REQUIRES_NEW, rollbackFor = OrderError.class)
    public void submit(Order order) {}

    @Scheduled(cron = "0 0 * * * *")
    @Async
    public void nightlyReconcile() {}
}
"""


def _parse(tmp_path: Path, package: str, name: str, body: str):
    package_dir = tmp_path.joinpath(*package.split("."))
    package_dir.mkdir(parents=True, exist_ok=True)
    path = package_dir / f"{name}.java"
    path.write_text(body)
    return JavaParser().parse(path)


# -- behavioral markers --


def test_transactional_attributes_are_captured(tmp_path: Path) -> None:
    document = _parse(tmp_path, "com.acme.service", "OrderService", _BEHAVIOR)
    markers = {(m.owner_qualified_name, m.marker): m for m in document.behavior_markers}

    method = markers[("com.acme.service.OrderService.submit(Order)", "transactional")]
    assert method.target == "method"
    assert method.attributes["propagation"] == "Propagation.REQUIRES_NEW"
    assert method.attributes["rollbackFor"] == "OrderError.class"

    klass = markers[("com.acme.service.OrderService", "transactional")]
    assert klass.target == "type"
    assert klass.attributes["readOnly"] is True


def test_scheduled_cron_and_async_are_extracted(tmp_path: Path) -> None:
    document = _parse(tmp_path, "com.acme.service", "OrderService", _BEHAVIOR)
    owner = "com.acme.service.OrderService.nightlyReconcile()"
    by_marker = {m.marker: m for m in document.behavior_markers if m.owner_qualified_name == owner}

    assert by_marker["scheduled"].attributes["cron"] == "0 0 * * * *"
    assert "async" in by_marker


# -- aspect advice --


def test_aspect_advice_and_pointcuts_are_extracted(tmp_path: Path) -> None:
    document = _parse(tmp_path, "com.acme.aop", "AuditAspect", _ASPECT)
    by_kind = {a.advice_kind: a for a in document.aop_advice}

    assert by_kind["pointcut"].pointcut_expr == "execution(* com.acme.service..*(..))"
    assert by_kind["around"].pointcut_expr == "serviceMethods()"
    assert by_kind["around"].pointcut_ref == "serviceMethods"
    assert by_kind["before"].pointcut_ref is None
    assert all(a.aspect_qualified_name == "com.acme.aop.AuditAspect" for a in document.aop_advice)


# -- AopResolver._assemble --


def _advice(advice_id, kind, expr, advice_qn="com.acme.aop.A.m()"):
    return {
        "id": advice_id,
        "kind": kind,
        "aspect": "com.acme.aop.A",
        "advice_qn": advice_qn,
        "expr": expr,
        "ref": None,
    }


def _method(qn, owner, anno_fqns=None):
    return {"qn": qn, "owner": owner, "anno_fqns": anno_fqns or []}


_METHODS = [
    _method("com.acme.service.OrderService.submit(Order)", "com.acme.service.OrderService"),
    _method("com.acme.service.OrderService.cancel(Long)", "com.acme.service.OrderService"),
    _method(
        "com.acme.web.OrderController.get(Long)",
        "com.acme.web.OrderController",
        ["org.springframework.transaction.annotation.Transactional"],
    ),
]


def test_execution_pointcut_matches_methods() -> None:
    advice = _advice("ad1", "around", "execution(* com.acme.service..*(..))")

    assembled = AopResolver._assemble([advice], _METHODS)

    assert {row["to"] for row in assembled.advises} == {
        "com.acme.service.OrderService.submit(Order)",
        "com.acme.service.OrderService.cancel(Long)",
    }
    assert assembled.reasons == [{"id": "ad1", "reason": None}]


def test_named_pointcut_reference_is_substituted() -> None:
    pointcut = _advice(
        "pc",
        "pointcut",
        "execution(* com.acme.web.*Controller.*(..))",
        advice_qn="com.acme.aop.A.controllers()",
    )
    around = _advice("ad2", "around", "controllers()")

    assembled = AopResolver._assemble([pointcut, around], _METHODS)

    assert {row["to"] for row in assembled.advises} == {"com.acme.web.OrderController.get(Long)"}


def test_annotation_designator_matches_annotated_methods() -> None:
    advice = _advice(
        "ad3", "before", "@annotation(org.springframework.transaction.annotation.Transactional)"
    )

    assembled = AopResolver._assemble([advice], _METHODS)

    assert {row["to"] for row in assembled.advises} == {"com.acme.web.OrderController.get(Long)"}


def test_unmatched_pointcut_is_left_unresolved_with_a_reason() -> None:
    advice = _advice("ad4", "after", "execution(* com.acme.nope..*(..))")

    assembled = AopResolver._assemble([advice], _METHODS)

    assert assembled.advises == []
    assert assembled.reasons == [
        {"id": "ad4", "reason": "no CodeEntity matched pointcut: execution(* com.acme.nope..*(..))"}
    ]


def test_negation_pointcut_is_reported_unsupported() -> None:
    advice = _advice("ad5", "around", "execution(* com.acme..*(..)) && !within(com.acme.aop..*)")

    assembled = AopResolver._assemble([advice], _METHODS)

    assert assembled.advises == []
    assert assembled.reasons[0]["reason"].startswith("unsupported pointcut expression:")

import hashlib

from pydantic import BaseModel, computed_field


class AopAdvice(BaseModel):
    """One piece of advice declared inside an `@Aspect` class.

    An `@Before` / `@After` / `@AfterReturning` / `@AfterThrowing` / `@Around`
    method, or a named `@Pointcut` method. `pointcut_expr` is the raw AspectJ
    pointcut string as written (`execution(* com.acme.service..*(..))`,
    `@annotation(org.springframework.transaction.annotation.Transactional)`,
    or a reference to a named pointcut like `orderServiceMethods()`).
    `pointcut_ref` is the bare name of a referenced `@Pointcut` method when the
    expression is just that call, so the `AopResolver` can substitute the real
    designator before matching `CodeEntity`s.

    Feeds `(:CodeEntity advice-method)-[:ADVICE_OF]->(:Advice)` from the writer
    and, after the resolver pass, `(:Advice)-[:ADVISES]->(:CodeEntity)` for
    every method the pointcut resolves to (best-effort string/glob match — no
    full AspectJ pointcut engine).
    """

    aspect_qualified_name: str
    advice_qualified_name: str
    # "before" | "after" | "after_returning" | "after_throwing" | "around" | "pointcut"
    advice_kind: str
    pointcut_expr: str
    pointcut_ref: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        key = "\x00".join((self.advice_qualified_name, self.advice_kind))
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

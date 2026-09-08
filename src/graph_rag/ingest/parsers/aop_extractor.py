from ..models import Annotation, AopAdvice, BehaviorMarker, CodeEntity

# annotation simple name → normalized behavior marker slug.
_BEHAVIOR_MARKERS: dict[str, str] = {
    "Transactional": "transactional",
    "Async": "async",
    "Scheduled": "scheduled",
    "Schedules": "scheduled",
    "Retryable": "retryable",
    "Cacheable": "cacheable",
    "CachePut": "cache_put",
    "CacheEvict": "cache_evict",
    "PreAuthorize": "pre_authorize",
    "PostAuthorize": "post_authorize",
    "Secured": "secured",
    "RolesAllowed": "roles_allowed",
}

# advice annotation simple name → normalized advice kind.
_ADVICE_KINDS: dict[str, str] = {
    "Before": "before",
    "After": "after",
    "AfterReturning": "after_returning",
    "AfterThrowing": "after_throwing",
    "Around": "around",
    "Pointcut": "pointcut",
}


class AopExtractor:
    """Derives `BehaviorMarker`s and `AopAdvice` from a parsed `.java` file's
    `CodeEntity` + `Annotation` lists — an aspect and its advice always live in
    one file, so this needs no cross-file resolution.

    * Behavioral markers: any `@Transactional` / `@Scheduled` / `@Async` /
      `@Retryable` / `@Cacheable` / `@PreAuthorize` / … on a type or method.
      The annotation's full attribute map is carried through
      (`propagation`, `readOnly`, `cron`, `fixedRate`, `maxAttempts`, …).
    * AOP advice: every advice / `@Pointcut` method of an `@Aspect` type, with
      its raw pointcut expression. Matching the expression to the `CodeEntity`s
      it advises is the `AopResolver`'s job (cross-file, post-ingest).
    """

    @classmethod
    def extract(
        cls, entities: list[CodeEntity], annotations: list[Annotation]
    ) -> tuple[list[BehaviorMarker], list[AopAdvice]]:
        by_owner: dict[str, list[Annotation]] = {}
        for annotation in annotations:
            by_owner.setdefault(annotation.owner_qualified_name, []).append(annotation)

        markers = cls._behavior_markers(annotations)
        advice = cls._aop_advice(entities, by_owner)
        return markers, advice

    # -- behavioral markers --

    @staticmethod
    def _behavior_markers(annotations: list[Annotation]) -> list[BehaviorMarker]:
        markers: list[BehaviorMarker] = []
        for annotation in annotations:
            if annotation.target.startswith("param:"):
                continue
            slug = _BEHAVIOR_MARKERS.get(annotation.name)
            if slug is None:
                continue
            markers.append(
                BehaviorMarker(
                    owner_qualified_name=annotation.owner_qualified_name,
                    target="type" if annotation.target == "type" else "method",
                    marker=slug,
                    attributes=dict(annotation.attributes),
                    line=annotation.line,
                )
            )
        return markers

    # -- aspect advice --

    @classmethod
    def _aop_advice(
        cls, entities: list[CodeEntity], by_owner: dict[str, list[Annotation]]
    ) -> list[AopAdvice]:
        aspect_types = {
            entity.qualified_name
            for entity in entities
            if entity.kind in ("class", "aspect")
            and any(a.name == "Aspect" for a in by_owner.get(entity.qualified_name, []))
        }
        if not aspect_types:
            return []

        advice: list[AopAdvice] = []
        for entity in entities:
            if entity.kind != "method" or entity.parent_qualified_name not in aspect_types:
                continue
            for annotation in by_owner.get(entity.qualified_name, []):
                kind = _ADVICE_KINDS.get(annotation.name)
                if kind is None:
                    continue
                expression = cls._pointcut_expression(annotation)
                advice.append(
                    AopAdvice(
                        aspect_qualified_name=entity.parent_qualified_name,
                        advice_qualified_name=entity.qualified_name,
                        advice_kind=kind,
                        pointcut_expr=expression,
                        pointcut_ref=cls._pointcut_ref(expression),
                    )
                )
        return advice

    @staticmethod
    def _pointcut_expression(annotation: Annotation) -> str:
        for key in ("value", "pointcut"):
            raw = annotation.attributes.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
            if isinstance(raw, (list, tuple)) and raw:
                return str(raw[0]).strip()
        return ""

    @staticmethod
    def _pointcut_ref(expression: str) -> str | None:
        """A pointcut expression that is only a call to a named `@Pointcut`
        method — `orderServiceMethods()` or `com.acme.Aspects.txMethods()` —
        with no AspectJ designator keyword. The resolver substitutes the real
        designator before matching.
        """
        stripped = expression.strip()
        if not stripped.endswith(")") or "(" not in stripped:
            return None
        head = stripped[: stripped.index("(")].strip()
        if not head or any(char in head for char in " \t&|!"):
            return None
        designators = ("execution", "within", "annotation", "target", "args", "this", "bean")
        if head.rsplit(".", 1)[-1] in designators:
            return None
        return head.rsplit(".", 1)[-1]

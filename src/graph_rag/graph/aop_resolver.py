import logging
import re
from typing import Any, LiteralString, NamedTuple, cast

from neo4j import Driver, ManagedTransaction

logger = logging.getLogger(__name__)

_ADVICE_NODES = """
MATCH (ad:Advice)
RETURN ad.id AS id, ad.kind AS kind, ad.aspect AS aspect,
       ad.advice_qualified_name AS advice_qn, ad.pointcut_expr AS expr,
       ad.pointcut_ref AS ref
"""

_CANDIDATE_METHODS = """
MATCH (e:CodeEntity)
WHERE e.kind IN ['method', 'constructor']
OPTIONAL MATCH (e)-[:ANNOTATED_WITH]->(a:Annotation)
RETURN e.qualified_name AS qn, e.parent_qualified_name AS owner,
       collect(DISTINCT a.fqn) AS anno_fqns
"""

_CLEAR_ADVISES = "MATCH (:Advice)-[r:ADVISES]->() DELETE r"

_MERGE_ADVISES = """
UNWIND $rows AS row
MATCH (ad:Advice {id: row.from})
MATCH (e:CodeEntity {qualified_name: row.to})
MERGE (ad)-[:ADVISES]->(e)
"""

_SET_ADVICE_REASON = """
UNWIND $rows AS row
MATCH (ad:Advice {id: row.id})
SET ad.unresolved_reason = row.reason
"""

_IDENT = r"[A-Za-z0-9_$]"
_DESIGNATOR = re.compile(
    r"^\s*(execution|within|@?annotation|target|this|args|bean)\s*\((.*)\)\s*$", re.DOTALL
)
_BARE_REF = re.compile(rf"^\s*(?:{_IDENT}+\.)*({_IDENT}+)\s*\(\s*\)\s*$")


class _Assembled(NamedTuple):
    advises: list[dict[str, str]]
    reasons: list[dict[str, str | None]]


class AopResolver:
    """Post-ingest pass that resolves every `@Aspect` advice's pointcut against
    the ingested `CodeEntity`s it advises.

    Best-effort AspectJ pointcut matching — no full pointcut engine:

    * `execution(<ret> <type>.<method>(<args>))` — glob-match the
      `<type>.<method>` pattern (`*` within a name, `..` across packages)
      against every method `qualified_name`.
    * `within(<type-pattern>)` — glob-match against the declaring type.
    * `@annotation(<FQN|simple>)` — methods carrying that annotation.
    * `&&` intersects, `||` unions; a named `@Pointcut()` reference is
      substituted once; `!` / unsupported designators leave the advice
      unresolved with a `reason`.

    Rebuilds `(:Advice)-[:ADVISES]->(:CodeEntity)` from scratch each run and
    records `Advice.unresolved_reason` (cleared to null when it now resolves).
    """

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def resolve(self) -> dict[str, int]:
        with self._driver.session() as session:
            result = session.execute_write(self._rebuild)
        logger.info("aop graph resolved: %s", result)
        return result

    @classmethod
    def _rebuild(cls, tx: ManagedTransaction) -> dict[str, int]:
        advice_rows = [dict(row) for row in tx.run(cast(LiteralString, _ADVICE_NODES))]
        tx.run(cast(LiteralString, _CLEAR_ADVISES))
        if not advice_rows:
            return {"advice": 0, "advises_edges": 0, "unresolved": 0}

        method_rows = [dict(row) for row in tx.run(cast(LiteralString, _CANDIDATE_METHODS))]
        assembled = cls._assemble(advice_rows, method_rows)
        if assembled.advises:
            tx.run(cast(LiteralString, _MERGE_ADVISES), rows=assembled.advises)
        if assembled.reasons:
            tx.run(cast(LiteralString, _SET_ADVICE_REASON), rows=assembled.reasons)
        unresolved = sum(1 for row in assembled.reasons if row["reason"] is not None)
        return {
            "advice": len(advice_rows),
            "advises_edges": len(assembled.advises),
            "unresolved": unresolved,
        }

    # -- assembly (pure — unit-tested without Neo4j) --

    @classmethod
    def _assemble(
        cls, advice_rows: list[dict[str, Any]], method_rows: list[dict[str, Any]]
    ) -> _Assembled:
        named_pointcuts: dict[str, str] = {}
        for row in advice_rows:
            if row.get("kind") == "pointcut":
                simple = cls._method_simple_name(row.get("advice_qn") or "")
                if simple and row.get("expr"):
                    named_pointcuts[simple] = row["expr"]

        advises: list[dict[str, str]] = []
        reasons: list[dict[str, str | None]] = []
        for row in advice_rows:
            if row.get("kind") == "pointcut":
                continue
            expression = (row.get("expr") or "").strip()
            if not expression:
                reasons.append({"id": row["id"], "reason": "empty pointcut expression"})
                continue
            resolved = cls._match_pointcut(expression, method_rows, named_pointcuts)
            if resolved is None:
                reasons.append(
                    {"id": row["id"], "reason": f"unsupported pointcut expression: {expression}"}
                )
                continue
            if not resolved:
                reasons.append(
                    {"id": row["id"], "reason": f"no CodeEntity matched pointcut: {expression}"}
                )
                continue
            for target in sorted(resolved):
                advises.append({"from": row["id"], "to": target})
            reasons.append({"id": row["id"], "reason": None})
        return _Assembled(advises, reasons)

    @classmethod
    def _match_pointcut(
        cls,
        expression: str,
        method_rows: list[dict[str, Any]],
        named_pointcuts: dict[str, str],
        depth: int = 0,
    ) -> set[str] | None:
        expression = expression.strip()
        if (
            expression.startswith("(")
            and expression.endswith(")")
            and _DESIGNATOR.match(expression) is None
        ):
            expression = expression[1:-1].strip()
        if "!" in expression:
            return None

        bare = _BARE_REF.match(expression)
        if bare is not None:
            if depth > 3 or bare.group(1) not in named_pointcuts:
                return None
            return cls._match_pointcut(
                named_pointcuts[bare.group(1)], method_rows, named_pointcuts, depth + 1
            )

        if "&&" in expression:
            result: set[str] | None = None
            for part in cls._split_top_level(expression, "&&"):
                matched = cls._match_pointcut(part, method_rows, named_pointcuts, depth + 1)
                if matched is None:
                    return None
                result = matched if result is None else (result & matched)
            return result or set()
        if "||" in expression:
            union: set[str] = set()
            for part in cls._split_top_level(expression, "||"):
                matched = cls._match_pointcut(part, method_rows, named_pointcuts, depth + 1)
                if matched is None:
                    return None
                union |= matched
            return union

        return cls._designator_match(expression, method_rows)

    @classmethod
    def _designator_match(cls, token: str, method_rows: list[dict[str, Any]]) -> set[str] | None:
        match = _DESIGNATOR.match(token)
        if match is None:
            return None
        kind, argument = match.group(1), match.group(2).strip()
        if kind == "execution":
            pattern = cls._execution_type_method_pattern(argument)
            regex = cls._pattern_to_regex(pattern)
            return {
                row["qn"] for row in method_rows if regex.fullmatch(cls._strip_params(row["qn"]))
            }
        if kind == "within":
            regex = cls._pattern_to_regex(argument.strip())
            return {
                row["qn"]
                for row in method_rows
                if row.get("owner") and regex.fullmatch(row["owner"])
            }
        if kind in ("annotation", "@annotation"):
            wanted = argument.strip().rsplit(".", 1)[-1]
            hits: set[str] = set()
            for row in method_rows:
                simples = {(fqn or "").rsplit(".", 1)[-1] for fqn in row.get("anno_fqns") or []}
                if argument.strip() in (row.get("anno_fqns") or []) or wanted in simples:
                    hits.add(row["qn"])
            return hits
        return None

    @staticmethod
    def _execution_type_method_pattern(argument: str) -> str:
        before_paren = argument.split("(", 1)[0].strip()
        parts = before_paren.split()
        pattern = parts[-1] if parts else "*"
        if "." not in pattern:
            return f"*.{pattern}"
        return pattern

    @staticmethod
    def _pattern_to_regex(pattern: str) -> re.Pattern[str]:
        out: list[str] = []
        index = 0
        while index < len(pattern):
            if pattern.startswith("..", index):
                out.append(r"\..*")
                index += 2
            elif pattern[index] == "*":
                out.append(r"[A-Za-z0-9_$]*")
                index += 1
            elif pattern[index] == ".":
                out.append(r"\.")
                index += 1
            elif pattern[index] == "+":
                index += 1
            else:
                out.append(re.escape(pattern[index]))
                index += 1
        return re.compile("".join(out))

    @staticmethod
    def _strip_params(qualified_name: str) -> str:
        return qualified_name.split("(", 1)[0]

    @staticmethod
    def _method_simple_name(qualified_name: str) -> str:
        head = qualified_name.split("(", 1)[0]
        return head.rsplit(".", 1)[-1]

    @staticmethod
    def _split_top_level(expression: str, operator: str) -> list[str]:
        parts: list[str] = []
        depth = 0
        current = ""
        index = 0
        while index < len(expression):
            char = expression[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            if depth == 0 and expression.startswith(operator, index):
                parts.append(current)
                current = ""
                index += len(operator)
                continue
            current += char
            index += 1
        if current.strip():
            parts.append(current)
        return parts

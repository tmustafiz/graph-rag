from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import yaml

from ..mcp_server.retriever import Retriever
from .eval_case import EvalCase
from .eval_case_result import EvalCaseResult

DEFAULT_EVAL_SET_PATH = Path(__file__).parent / "retrieval_eval_set.yaml"

# Fixture corpus the eval is written against. `grag-mcp eval-retrieval` ingests
# this first so the eval is self-contained. Kept repo-root-relative so the
# ingested Source.path matches `expected_source_path` in the eval set — run
# `grag-mcp eval-retrieval` / `make eval` from the repo root.
EVAL_CORPUS_DIR = Path("src/graph_rag/eval/corpus")


def _first_rank(hits: Sequence[Any], matches: Callable[[Any], bool]) -> int | None:
    """1-indexed position of the first hit satisfying `matches`, or `None`."""
    return next((rank for rank, hit in enumerate(hits, start=1) if matches(hit)), None)


class RetrievalEvaluator:
    """Runs a small hand-written set of retrieval regression cases against the
    `Retriever` search methods — catches regressions when chunking / embedding /
    ranking logic changes. Needs a live Neo4j (via `retriever`), so it's a CLI
    command (`grag-mcp eval-retrieval`), not part of the pytest suite.
    """

    def __init__(self, retriever: Retriever) -> None:
        self._retriever = retriever

    def run(self, cases: list[EvalCase]) -> list[EvalCaseResult]:
        results = []
        for case in cases:
            best_rank = self._best_rank(case)
            passed = (best_rank is not None) == case.expect_match
            results.append(EvalCaseResult(case=case, passed=passed, best_rank=best_rank))
        return results

    def _best_rank(self, case: EvalCase) -> int | None:
        if case.tool == "search":
            hits = self._retriever.search(case.query, top_k=case.top_k)
            wanted_breadcrumb = (case.expected_breadcrumb_contains or "").lower()
            return _first_rank(
                hits,
                lambda hit: (
                    hit.source_path == case.expected_source_path
                    and wanted_breadcrumb in hit.breadcrumb.lower()
                ),
            )
        if case.tool == "search_code":
            hits = self._retriever.search_code(case.query, top_k=case.top_k)
            wanted_name = (case.expected_qualified_name_contains or "").lower()
            return _first_rank(hits, lambda hit: wanted_name in hit.qualified_name.lower())
        hits = self._retriever.search_policies(case.query, top_k=case.top_k)
        return _first_rank(hits, lambda hit: hit.id == case.expected_policy_id)

    @staticmethod
    def load_cases(path: Path | None = None) -> list[EvalCase]:
        rows = yaml.safe_load((path or DEFAULT_EVAL_SET_PATH).read_text())
        return [EvalCase.model_validate(row) for row in rows]

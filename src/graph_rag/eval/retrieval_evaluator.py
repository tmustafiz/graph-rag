from pathlib import Path

import yaml

from ..mcp_server.retriever import Retriever
from .eval_case import EvalCase
from .eval_case_result import EvalCaseResult

DEFAULT_EVAL_SET_PATH = Path(__file__).parent / "retrieval_eval_set.yaml"


class RetrievalEvaluator:
    """Runs a small hand-written set of retrieval regression cases against
    `Retriever.search()` — catches regressions when chunking/embedding logic
    changes. Needs a live Neo4j (via `retriever`), so it's a CLI command
    (`graph-rag eval-retrieval`), not part of the pytest suite.
    """

    def __init__(self, retriever: Retriever) -> None:
        self._retriever = retriever

    def run(self, cases: list[EvalCase]) -> list[EvalCaseResult]:
        results = []
        for case in cases:
            hits = self._retriever.search(case.query, top_k=case.top_k)
            best_rank = next(
                (
                    rank
                    for rank, hit in enumerate(hits, start=1)
                    if hit.source_path == case.expected_source_path
                    and case.expected_breadcrumb_contains.lower() in hit.breadcrumb.lower()
                ),
                None,
            )
            results.append(
                EvalCaseResult(case=case, passed=best_rank is not None, best_rank=best_rank)
            )
        return results

    @staticmethod
    def load_cases(path: Path | None = None) -> list[EvalCase]:
        rows = yaml.safe_load((path or DEFAULT_EVAL_SET_PATH).read_text())
        return [EvalCase.model_validate(row) for row in rows]

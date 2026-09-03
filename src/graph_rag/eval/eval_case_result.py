from pydantic import BaseModel

from .eval_case import EvalCase


class EvalCaseResult(BaseModel):
    """Outcome of running one `EvalCase` against a `Retriever` search method."""

    case: EvalCase
    passed: bool
    best_rank: int | None = None  # 1-indexed position of the first matching hit, if any

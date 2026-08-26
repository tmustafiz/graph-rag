from pydantic import BaseModel


class EvalCase(BaseModel):
    """One hand-written retrieval regression case for `RetrievalEvaluator`."""

    query: str
    expected_source_path: str
    expected_breadcrumb_contains: str
    top_k: int = 5

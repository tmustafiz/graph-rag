from typing import Literal

from pydantic import BaseModel, model_validator

EvalTool = Literal["search", "search_code", "search_policies"]

_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "search": ("expected_source_path", "expected_breadcrumb_contains"),
    "search_code": ("expected_qualified_name_contains",),
    "search_policies": ("expected_policy_id",),
}


class EvalCase(BaseModel):
    """One hand-written retrieval regression case for `RetrievalEvaluator`.

    `tool` picks which retriever method the case exercises and therefore which
    `expected_*` field(s) it checks. Set `expect_match: false` for a negative
    case — one where *none* of the top-`top_k` hits should match the
    expectation.
    """

    query: str
    tool: EvalTool = "search"
    top_k: int = 5
    expect_match: bool = True

    # tool == "search"
    expected_source_path: str | None = None
    expected_breadcrumb_contains: str | None = None
    # tool == "search_code"
    expected_qualified_name_contains: str | None = None
    # tool == "search_policies"
    expected_policy_id: str | None = None

    @model_validator(mode="after")
    def _check_expectation_fields_present(self) -> "EvalCase":
        missing = [name for name in _REQUIRED_FIELDS[self.tool] if getattr(self, name) is None]
        if missing:
            raise ValueError(
                f"{self.tool} case {self.query!r} is missing required field(s): "
                + ", ".join(missing)
            )
        return self

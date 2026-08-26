from pydantic import BaseModel


class CodeCentralityResult(BaseModel):
    """One `CodeEntity` ranked by PageRank over the `CALLS`/`IMPORTS` graph —
    higher `pagerank` means more heavily depended-upon (called/imported by
    more of the codebase), and riskier to change carelessly.
    """

    qualified_name: str
    name: str
    kind: str
    file_path: str | None = None
    pagerank: float

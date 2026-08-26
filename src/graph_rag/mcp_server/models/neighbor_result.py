from pydantic import BaseModel


class NeighborResult(BaseModel):
    """One node reached from a `get_neighbors` traversal."""

    relationship_type: str
    direction: str  # "outgoing" | "incoming"
    node_label: str
    node_key: str
    summary: str | None = None

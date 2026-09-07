from pydantic import BaseModel


class ExternalArtifact(BaseModel):
    """A declared third-party dependency, keyed by `gav` — `group:artifact`
    (version dropped from the key so re-declared versions collapse to one
    node). Feeds `(Module)-[:DEPENDS_ON_EXTERNAL {gav, scope}]->(:ExternalArtifact)`.
    """

    gav: str
    group: str | None = None
    artifact: str | None = None
    version: str | None = None

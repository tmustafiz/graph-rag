from pydantic import BaseModel


class BeanEdge(BaseModel):
    """One end of an `INJECTS` / `PRODUCES` edge reported by `get_beans_for`."""

    bean_id: str
    name: str
    stereotype: str | None = None
    # `INJECTS` only: constructor / field / setter / xml-constructor / xml-property.
    via: str | None = None

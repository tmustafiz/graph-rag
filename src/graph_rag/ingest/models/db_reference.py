from typing import Literal

from pydantic import BaseModel


class DbReference(BaseModel):
    """A standalone foreign-key edge whose endpoints are named by qualified
    name only — emitted when a `FOREIGN KEY` is declared away from the nodes it
    connects (an `ALTER TABLE … ADD CONSTRAINT` in a different migration file
    from the `CREATE TABLE`), so the edge still lands after the target table is
    ingested. `level` picks `DbColumn`→`DbColumn` vs `DbTable`→`DbTable`.
    """

    from_qualified_name: str
    to_qualified_name: str
    level: Literal["column", "table"]

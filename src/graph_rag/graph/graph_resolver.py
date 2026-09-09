import logging

from neo4j import Driver, ManagedTransaction

logger = logging.getLogger(__name__)


class GraphResolver:
    """Common shell for a post-ingest graph pass: hold the driver, run
    `_rebuild` in a single write transaction, and log the stats dict it
    returns. A subclass sets `_log_label` and implements
    `_rebuild(tx) -> dict[str, int]` (idempotent — it clears and rebuilds its
    own edges each run). A pass that needs more than one write transaction
    overrides `resolve` itself.
    """

    _log_label: str = ""

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def resolve(self) -> dict[str, int]:
        with self._driver.session() as session:
            result = session.execute_write(self._rebuild)
        logger.info("%s graph resolved: %s", self._log_label, result)
        return result

    @classmethod
    def _rebuild(cls, tx: ManagedTransaction) -> dict[str, int]:
        raise NotImplementedError

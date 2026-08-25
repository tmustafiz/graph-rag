from collections.abc import Generator
from contextlib import contextmanager

from neo4j import Driver, GraphDatabase

from graph_rag.settings import settings


def get_driver() -> Driver:
    return GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )


@contextmanager
def driver_session() -> Generator[Driver]:
    driver = get_driver()
    try:
        yield driver
    finally:
        driver.close()


def check_connectivity() -> bool:
    with driver_session() as driver:
        driver.verify_connectivity()
        return True

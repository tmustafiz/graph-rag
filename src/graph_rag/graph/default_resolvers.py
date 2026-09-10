from __future__ import annotations

from typing import TYPE_CHECKING

from neo4j import Driver

from .aop_resolver import AopResolver
from .camel_resolver import CamelResolver
from .mybatis_resolver import MyBatisResolver
from .project_model_resolver import ProjectModelResolver
from .service_call_resolver import ServiceCallResolver
from .spring_bean_resolver import SpringBeanResolver
from .spring_data_resolver import SpringDataResolver
from .spring_injection_resolver import SpringInjectionResolver
from .spring_xml_resolver import SpringXmlResolver

if TYPE_CHECKING:
    from ..ingestion_pipeline import PostIngestResolver


def build_default_resolvers(driver: Driver) -> list[PostIngestResolver]:
    """The ordered post-ingest graph passes the pipeline runs after every
    ingest (directory or single file). Order matters — each pass reads the
    graph the previous ones built. The single source of truth for the list;
    `cli.py` (ingest / eval / serve) and any other entry point call this so a
    new resolver can't be added to one path and forgotten in another.
    """
    return [
        ProjectModelResolver(driver),
        SpringBeanResolver(driver),
        SpringXmlResolver(driver),
        SpringDataResolver(driver),
        SpringInjectionResolver(driver),
        AopResolver(driver),
        ServiceCallResolver(driver),
        MyBatisResolver(driver),
        CamelResolver(driver),
    ]

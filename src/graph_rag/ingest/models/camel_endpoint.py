from pydantic import BaseModel


class CamelEndpoint(BaseModel):
    """An Apache Camel endpoint URI — `jms:queue:orders`, `direct:process`,
    `http://svc/api`, `bean:orderService?method=handle`.

    `uri` is the graph key, so a `.to("direct:foo")` producer and a
    `from("direct:foo")` consumer route MERGE onto the same node — that is what
    pairs internal routes:
    `(:Route)-[:TO]->(:CamelEndpoint)-[:CONSUMED_BY]->(:Route)`. `scheme` is the
    part before the first `:`.
    """

    uri: str
    scheme: str

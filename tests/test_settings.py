from graph_rag.settings import Settings


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.neo4j_uri.startswith("bolt://")
    assert settings.mcp_port == 8765

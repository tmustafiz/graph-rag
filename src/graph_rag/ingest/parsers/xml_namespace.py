def local_name(tag: str) -> str:
    """The local name of an `ElementTree` tag — `{ns}bean` → `bean`, `bean` →
    `bean`. `ElementTree` stores a namespaced tag as `{uri}local`.
    """
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def namespace(tag: str) -> str:
    """The namespace URI of an `ElementTree` tag — `{uri}bean` → `uri`, an
    unqualified `bean` → `""`.
    """
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""

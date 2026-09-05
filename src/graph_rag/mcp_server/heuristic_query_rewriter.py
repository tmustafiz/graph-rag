import re

from .query_rewriter import DEFAULT_MAX_QUERIES, QueryRewriter, normalize_variants

# Small, deliberately domain-general starter map: acronyms this project's own
# corpus (graph RAG over docs, Python, and Checkov infra policies) tends to see
# spelled both ways. Point `GRAG_QUERY_REWRITE_SYNONYMS` at a JSON file to add
# project-specific terms — those are merged over these, so a downstream corpus
# can override any entry.
_BUILTIN_SYNONYMS: dict[str, str] = {
    "rag": "retrieval augmented generation",
    "mcp": "model context protocol",
    "iac": "infrastructure as code",
    "k8s": "kubernetes",
    "ci": "continuous integration",
    "cd": "continuous delivery",
    "auth": "authentication",
    "authz": "authorization",
    "db": "database",
    "vpc": "virtual private cloud",
    "iam": "identity and access management",
    "vuln": "vulnerability",
    "repo": "repository",
    "config": "configuration",
}

# Conjunctions that tend to join two independently-searchable asks in one
# question. Split only when both sides are substantial (see `_MIN_SPLIT_WORDS`)
# so "read and write" or "auth and authz" isn't torn into fragments.
_SPLIT_PATTERN = re.compile(r"\s+(?:and|&|;|,|as well as)\s+", flags=re.IGNORECASE)
_MIN_SPLIT_WORDS = 3

_WORD_PATTERN = re.compile(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*")


class HeuristicQueryRewriter(QueryRewriter):
    """Offline query expansion — no network, no API key, no model.

    Two rules, applied independently to the original query:

    - **Acronym / jargon expansion.** Any whole word that matches the synonym
      map (built-in plus an optional `GRAG_QUERY_REWRITE_SYNONYMS` JSON file)
      is swapped for its expansion, producing one extra variant per distinct
      hit.
    - **Multi-part splitting.** A query joined by `and` / `;` / `,` / `as well
      as` is split into its parts when each part carries at least
      `_MIN_SPLIT_WORDS` words, so a compound question becomes one sub-query
      per ask.

    Cheap enough to be the default backend when `GRAG_QUERY_REWRITE` is on; the
    LLM backend is opt-in on top.
    """

    def __init__(
        self,
        synonyms: dict[str, str] | None = None,
        max_queries: int = DEFAULT_MAX_QUERIES,
    ) -> None:
        overrides = {term.lower(): expansion for term, expansion in (synonyms or {}).items()}
        self._synonyms = {**_BUILTIN_SYNONYMS, **overrides}
        self._max_queries = max_queries

    def rewrite(self, query: str) -> list[str]:
        variants = [*self._expand_acronyms(query), *self._split_multipart(query)]
        return normalize_variants(query, variants, self._max_queries)

    def _expand_acronyms(self, query: str) -> list[str]:
        hits = {
            match.group(0).lower()
            for match in _WORD_PATTERN.finditer(query)
            if match.group(0).lower() in self._synonyms
        }
        expansions = []
        for term in hits:
            pattern = re.compile(rf"\b{re.escape(term)}\b", flags=re.IGNORECASE)
            expansions.append(pattern.sub(self._synonyms[term], query))
        return expansions

    @staticmethod
    def _split_multipart(query: str) -> list[str]:
        parts = [part.strip() for part in _SPLIT_PATTERN.split(query) if part.strip()]
        if len(parts) < 2:
            return []
        if any(len(_WORD_PATTERN.findall(part)) < _MIN_SPLIT_WORDS for part in parts):
            return []
        return parts

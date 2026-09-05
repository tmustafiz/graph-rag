from abc import ABC, abstractmethod

# A generous ceiling on the original-plus-variants list a rewriter may return.
# Each extra variant is another full hybrid-search round trip in `Retriever`, so
# the point is to keep a misconfigured or over-eager backend from fanning a
# single `search` call into dozens of Neo4j queries.
DEFAULT_MAX_QUERIES = 3


class QueryRewriter(ABC):
    """Turns one user query into a short list of search-query variants.

    A rewriter recovers recall on under-specified or jargon-mismatched queries
    by expanding acronyms, splitting a multi-part question into independent
    sub-queries, and/or paraphrasing toward the vocabulary of the ingested
    corpus. `Retriever` runs hybrid search for every returned variant and fuses
    the hit sets before reranking/truncation.

    Implementations MUST NOT raise: a backend that fails for any reason
    (network error, malformed response, ...) returns `[query]` so retrieval
    degrades to the unrewritten query instead of failing the search.
    """

    @abstractmethod
    def rewrite(self, query: str) -> list[str]:
        """Return `query` plus 0 or more variants, the original always first,
        de-duplicated, and never longer than the configured maximum.
        """


def normalize_variants(query: str, variants: list[str], max_queries: int) -> list[str]:
    """Shared post-processing every `QueryRewriter` applies to its raw output:
    force the original query first, drop blanks and case-insensitive duplicates,
    and cap the list at `max_queries` (at least 1 — the original always survives).
    """
    ordered = [query, *variants]
    seen: set[str] = set()
    result: list[str] = []
    for candidate in ordered:
        cleaned = candidate.strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result[: max(max_queries, 1)]

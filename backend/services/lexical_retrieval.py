from __future__ import annotations

import re


_STOP_WORDS = frozenset({
    "a", "about", "after", "all", "also", "am", "an", "and", "any", "are",
    "as", "at", "be", "because", "been", "before", "being", "between", "but",
    "by", "can", "could", "did", "do", "does", "for", "from", "had", "has",
    "have", "he", "her", "here", "hers", "him", "his", "how", "i", "if", "in",
    "into", "is", "it", "its", "just", "me", "might", "more", "most", "my",
    "of", "on", "or", "our", "ours", "please", "should", "so", "some", "such",
    "than", "that", "the", "their", "them", "then", "there", "these", "they",
    "this", "those", "through", "to", "too", "up", "us", "very", "was", "we",
    "were", "what", "when", "where", "which", "who", "why", "will", "with",
    "would", "you", "your", "yours", "mujhe", "mera", "meri", "mere", "hai",
    "hain", "ho", "ka", "ki", "ke", "ko", "mein", "me", "par", "pe", "se",
    "aur", "kya", "kar", "karo", "batao", "bataye", "please",
})


def lexical_terms(text: str) -> set[str]:
    """Normalize useful words for a low-memory retrieval fallback."""
    return {
        token
        for token in re.findall(r"[^\W_]{2,}", str(text or "").casefold(), flags=re.UNICODE)
        if token not in _STOP_WORDS and not token.isdigit()
    }


def lexical_relevance(query: str, content: str) -> float:
    """Return a lightweight 0..1 overlap score; zero means no shared terms."""
    query_terms = lexical_terms(query)
    if not query_terms:
        return 0.0

    content_terms = lexical_terms(content)
    overlap = query_terms.intersection(content_terms)
    if not overlap:
        return 0.0

    coverage = len(overlap) / len(query_terms)
    density = len(overlap) / max(1, len(content_terms))
    return min(1.0, 0.8 * coverage + 0.2 * density)

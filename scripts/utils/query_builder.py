from __future__ import annotations


def build_candidate_search_query(language: str) -> str:
    normalized = language.strip()
    if normalized not in {"JavaScript", "TypeScript"}:
        raise ValueError(f"Unsupported candidate discovery language: {language!r}")

    # Broad discovery query: public repositories with the target language and a minimal activity signal.
    # Exact query strings are logged by the discovery script.
    return f"language:{normalized} is:public stars:>=1"

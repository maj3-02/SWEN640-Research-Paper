from __future__ import annotations

import pytest

from scripts.utils.query_builder import build_candidate_search_query


@pytest.mark.parametrize(
    "language,expected",
    [
        ("JavaScript", "language:JavaScript is:public stars:>=1"),
        ("TypeScript", "language:TypeScript is:public stars:>=1"),
    ],
)
def test_build_candidate_search_query(language: str, expected: str) -> None:
    assert build_candidate_search_query(language) == expected


def test_build_candidate_search_query_rejects_unknown_language() -> None:
    with pytest.raises(ValueError):
        build_candidate_search_query("Python")

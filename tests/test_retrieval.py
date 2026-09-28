"""Contextual BM25 검색 엔진 토큰화·랭킹 테스트 (네트워크 불필요)."""
from __future__ import annotations

from policy_mcp.retrieval import BM25Index, Chunk, bm25_search, tokenize


def test_tokenize_korean_ngrams_and_alnum():
    toks = tokenize("청년월세 Kpass")
    assert "청년월세" in toks      # 원형
    assert "청년" in toks          # 2-gram
    assert "kpass" in toks         # 영숫자 소문자


def test_chunk_index_text_includes_context():
    c = Chunk(id="x", title="T", source="S", context="맥락블러브", body="본문내용")
    assert "맥락블러브" in c.index_text()
    assert "본문내용" in c.index_text()


def test_bm25_search_ranks_relevant_first():
    chunks = [
        Chunk(id="a", title="월세지원", source="s", context="", body="무주택 청년 월세 지원 20만원"),
        Chunk(id="b", title="교통", source="s", context="", body="대중교통 환급 K패스"),
    ]
    hits = bm25_search("월세 지원", chunks, k=2)
    assert hits and hits[0][1].id == "a"


def test_bm25_empty_index_returns_empty():
    assert BM25Index([]).search("무엇이든", 3) == []


def test_bm25_no_match_returns_empty():
    chunks = [Chunk(id="a", title="월세", source="s", context="", body="월세 지원")]
    assert bm25_search("zzz없는단어qwerty", chunks, 3) == []

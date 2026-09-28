"""Contextual BM25 검색 엔진 (RAG / contextual retrieval).

Anthropic의 Contextual Retrieval 기법을 따른다: 각 청크에 '맥락 블러브'(이 청크가
문서 내에서 무엇·어디인지 1~2문장)를 본문 앞에 붙여 인덱싱 → 짧은 청크의 검색 누락을 줄임.
검색은 순수 파이썬 Okapi BM25. 한국어는 형태소 분석기 없이 문자 n-gram + 공백 토큰으로
견고하게 처리한다. 외부 의존성/네트워크 0 → p99 안전, 카카오-clean.

설계 메모(MCP 원칙): 서버는 '관련 근거(청크) 검색'만 한다. 최종 답변/종합은 호스트 LLM.
도메인 무관 모듈 — mobility_mcp에서 그대로 이식(청년정책 코퍼스에도 동일 적용).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[0-9a-z]+|[가-힣]+")


@dataclass
class Chunk:
    """검색 단위. index_text()가 실제 인덱싱 대상(맥락 블러브 포함)."""
    id: str
    title: str
    source: str
    context: str          # 맥락 블러브 (contextual retrieval)
    body: str
    domain: str = ""

    def index_text(self) -> str:
        return f"{self.context}\n{self.title}\n{self.body}"

    def as_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "source": self.source,
                "context": self.context, "text": self.body, "domain": self.domain}


def _ngrams(s: str, n: int) -> list[str]:
    return [s[i:i + n] for i in range(len(s) - n + 1)] if len(s) >= n else [s]


def tokenize(text: str) -> list[str]:
    """한국어 견고 토큰화: 한글은 원형 + 2/3-gram, 영숫자는 소문자 원형."""
    toks: list[str] = []
    for m in _TOKEN_RE.findall(text.lower()):
        if "가" <= m[0] <= "힣":          # 한글 음절 런
            toks.append(m)
            toks += _ngrams(m, 2)
            if len(m) >= 3:
                toks += _ngrams(m, 3)
        else:
            toks.append(m)
    return toks


class BM25Index:
    """작은 코퍼스용 인메모리 Okapi BM25."""

    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self._docs = [tokenize(c.index_text()) for c in chunks]
        self._len = [len(d) for d in self._docs]
        self.N = len(self._docs)
        self._avgdl = (sum(self._len) / self.N) if self.N else 0.0
        self._tf: list[dict[str, int]] = []
        self._df: dict[str, int] = {}
        for d in self._docs:
            counts: dict[str, int] = {}
            for t in d:
                counts[t] = counts.get(t, 0) + 1
            self._tf.append(counts)
            for t in counts:
                self._df[t] = self._df.get(t, 0) + 1

    def _idf(self, term: str) -> float:
        n = self._df.get(term, 0)
        return math.log(1 + (self.N - n + 0.5) / (n + 0.5))

    def _score(self, q_tokens: list[str], i: int) -> float:
        tf, dl = self._tf[i], self._len[i]
        s = 0.0
        for t in q_tokens:
            f = tf.get(t, 0)
            if not f:
                continue
            denom = f + self.k1 * (1 - self.b + self.b * dl / self._avgdl) if self._avgdl else 1
            s += self._idf(t) * (f * (self.k1 + 1)) / denom
        return s

    def search(self, query: str, k: int = 4) -> list[tuple[float, Chunk]]:
        if not self.N:
            return []
        q = tokenize(query)
        scored = [(self._score(q, i), self.chunks[i]) for i in range(self.N)]
        scored = [(round(s, 4), c) for s, c in scored if s > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:k]


def bm25_search(query: str, chunks: list[Chunk], k: int = 4) -> list[tuple[float, Chunk]]:
    """소규모/일회성(예: 사용자별 메모리) 검색용 — 매번 임시 인덱스 구축."""
    return BM25Index(chunks).search(query, k)

"""정책 검색 서비스 — 내장 코퍼스 BM25 + (키 있으면) 온통청년 API 융합.

- 내장 코퍼스 인덱스는 첫 사용 시 한 번 구축(인메모리, 네트워크 0). 작은 코퍼스라 <10ms.
- 서버는 근거·구조화 조건을 반환하고, 최종 안내 문구는 호스트 LLM 이 종합한다.

융합 랭킹 설계(라이브 파묻힘 방지):
  - 큐레이션(coprus) 결과는 source="curated", eligibility_check="structured"(check_eligibility 로 판정 가능).
  - 라이브(온통청년 API) 결과는 source="live", eligibility_check="manual"(조건 원문 기반 판단).
  - 라이브 hit 가 있으면 상위 k 안에 라이브를 최소 _LIVE_SLOTS 개 '보장'하고,
    큐레이션과 라이브를 교차(weave)해 라이브가 코퍼스에 완전히 파묻히지 않게 한다.
  - 같은 정책이 코퍼스·라이브에 모두 있으면 정책명 정규화로 dedupe(큐레이션 우선).
"""
from __future__ import annotations

import re
from functools import lru_cache

from . import policy_corpus
from .clients import youthcenter
from .retrieval import BM25Index

# 상위 k 안에서 라이브에 '보장'하는 최소 슬롯 수(라이브 hit 가 있을 때). 나머지는 큐레이션.
_LIVE_SLOTS = 2
_NORM_RE = re.compile(r"[\s()（）\[\]·・,./-]+")


@lru_cache(maxsize=1)
def _index() -> BM25Index:
    return BM25Index(policy_corpus.all_chunks())


def _norm_name(name: str) -> str:
    """정책명 정규화(dedupe 용): 소문자 + 공백/괄호/구두점 제거."""
    return _NORM_RE.sub("", (name or "").lower())


def corpus_search(query: str, region: str | None = None, category: str | None = None, k: int = 6) -> list[dict]:
    """내장 코퍼스에서 질의 관련 정책 top-k(구조화 detail + score + 태그)."""
    hits = _index().search(query, max(k * 2, k))
    out: list[dict] = []
    for score, chunk in hits:
        p = policy_corpus.get_policy(chunk.id)
        if p is None:
            continue
        if region:
            r = region.replace(" ", "")
            if p.regions and not any(r in x.replace(" ", "") or x.replace(" ", "") in r for x in p.regions):
                continue
        if category and category not in p.category and category not in p.subcategory:
            continue
        out.append({
            **p.detail(),
            "score": score,
            "origin": "corpus",
            "source": "curated",             # 내장 큐레이션 코퍼스
            "eligibility_check": "structured",  # check_eligibility 로 구조화 판정 가능
        })
        if len(out) >= k:
            break
    return out


def _tag_live(items: list[dict]) -> list[dict]:
    """라이브 API 아이템에 태그 부여(source=live, eligibility_check=manual)."""
    tagged: list[dict] = []
    for it in items:
        tagged.append({
            **it,
            "origin": "youthcenter_api",
            "source": "live",              # 온통청년 라이브 API
            "eligibility_check": "manual",  # 구조화 판정 불가 → 호스트가 조건 원문으로 판단
        })
    return tagged


def _dedupe_live(live: list[dict], curated: list[dict]) -> list[dict]:
    """라이브를 큐레이션과 dedupe(정책명 정규화 기준, 큐레이션 우선) + 라이브 내부 중복 제거."""
    seen_names = {_norm_name(c.get("name", "")) for c in curated}
    seen_ids = {c.get("policy_id") for c in curated}
    out: list[dict] = []
    for it in live:
        nm = _norm_name(it.get("name", ""))
        pid = it.get("policy_id")
        if not it.get("name"):
            continue
        if nm in seen_names or (pid and pid in seen_ids):
            continue
        seen_names.add(nm)
        if pid:
            seen_ids.add(pid)
        out.append(it)
    return out


def _weave(curated: list[dict], live: list[dict]) -> list[dict]:
    """큐레이션과 라이브를 교차 병합(curated[0], live[0], curated[1], live[1], …).

    라이브가 상위에 확실히 노출되도록 하되, 큐레이션을 먼저 시작해 구조화 판정 가능한
    결과를 우선 보여준다. 두 리스트 길이가 달라도 남는 쪽을 뒤에 이어 붙인다.
    """
    out: list[dict] = []
    ci = li = 0
    while ci < len(curated) or li < len(live):
        if ci < len(curated):
            out.append(curated[ci]); ci += 1
        if li < len(live):
            out.append(live[li]); li += 1
    return out


def _fuse(curated: list[dict], live: list[dict], k: int) -> list[dict]:
    """상위 k 구성: 라이브 hit 가 있으면 최소 _LIVE_SLOTS 개를 보장하고 교차 병합한다."""
    if not live:
        return curated[:k]

    n_live = min(_LIVE_SLOTS, len(live), k)
    n_curated = min(len(curated), k - n_live)
    # 큐레이션이 부족하면 남는 슬롯을 라이브에 되돌려준다(라이브가 더 많이 노출).
    if n_curated < k - n_live:
        n_live = min(len(live), k - n_curated)
    return _weave(curated[:n_curated], live[:n_live])[:k]


async def search(
    api_key: str | None,
    query: str,
    region: str | None = None,
    category: str | None = None,
    k: int = 6,
) -> dict:
    """온통청년 API(키 있으면) + 내장 코퍼스 BM25 검색을 융합한다.

    - 큐레이션 결과: source="curated", eligibility_check="structured"(check_eligibility 대상).
    - 라이브 결과: source="live", eligibility_check="manual"(조건 원문 기반 판단).
    - 라이브 hit 는 상위 k 에서 최소 _LIVE_SLOTS 개 보장 → 코퍼스에 파묻히지 않음.
    - 정책명 정규화로 dedupe(큐레이션 우선).
    """
    corpus_hits = corpus_search(query, region, category, k)

    api = await youthcenter.search_policies(
        api_key, query=query, category=category, region=region, page_size=k)

    live_on = not api.get("is_mock", True)
    live_items = _dedupe_live(_tag_live(api.get("items", [])), corpus_hits) if live_on else []

    results = _fuse(corpus_hits, live_items, k)
    curated_count = sum(1 for r in results if r.get("source") == "curated")
    live_count = sum(1 for r in results if r.get("source") == "live")

    return {
        "query": query,
        "curated_count": curated_count,
        "live_count": live_count,
        # 라이브면 API totCount(질의 전체 매칭 건수), 아니면 노출된 큐레이션 수.
        "total_available": api.get("total_count") if live_on else curated_count,
        "is_mock": not live_on,
        "results": results,
        "count": len(results),
        "data_source": {
            "corpus_hits": len(corpus_hits),
            "live_api": live_on,
            "live_available": len(live_items),
            "api_note": api.get("note", ""),
        },
        "note": ("각 result 는 source(curated=내장 큐레이션 / live=온통청년 라이브 API)와 "
                 "eligibility_check(structured=check_eligibility 로 자격 판정 가능 / "
                 "manual=조건 원문 기반 판단) 태그를 가진다. structured 정책은 policy_id 로 "
                 "check_eligibility 를 호출해 적격 여부를 판정하고, manual(라이브) 정책은 "
                 "조건 원문(summary·apply_url)으로 판단하라. 라이브 API 미연동 시 내장 대표 정책으로 제한된다."),
    }

"""검색 융합 랭킹 테스트 — 코퍼스+라이브 태그·dedupe·라이브 보장 (네트워크 불필요).

라이브 API 는 monkeypatch 로 결정론적 mock 을 주입한다(is_mock=False 로 '라이브'인 척).
"""
from __future__ import annotations

from policy_mcp import policies
from policy_mcp.clients import youthcenter


def _live_result(items, total_count=1234):
    """youthcenter.search_policies 가 반환하는 '라이브' 응답 형태."""
    return {
        "items": items,
        "count": len(items),
        "total_count": total_count,
        "is_mock": False,
        "source": "테스트 라이브",
        "note": "test-live",
    }


async def test_no_key_curated_only():
    """키 없음(mock 폴백) → 모든 결과 curated/structured, live_count=0, is_mock=True."""
    r = await policies.search(None, "월세 지원", k=6)
    assert r["results"], "결과가 비어있으면 안 됨"
    assert all(x["source"] == "curated" for x in r["results"])
    assert all(x["eligibility_check"] == "structured" for x in r["results"])
    assert r["live_count"] == 0
    assert r["curated_count"] == len(r["results"])
    assert r["is_mock"] is True
    # 태그 안내가 note 에 포함
    assert "structured" in r["note"] and "manual" in r["note"]


async def test_live_items_included_and_tagged(monkeypatch):
    """라이브 주입 시 라이브 항목이 결과에 포함되고 source=live/eligibility_check=manual 태그."""
    live_items = [
        {"policy_id": "L1", "name": "청년 라이브 정책 A", "summary": "라이브 A"},
        {"policy_id": "L2", "name": "청년 라이브 정책 B", "summary": "라이브 B"},
    ]

    async def fake(*a, **k):
        return _live_result(live_items)

    monkeypatch.setattr(youthcenter, "search_policies", fake)
    r = await policies.search("KEY", "월세 지원", k=6)

    ids = {x.get("policy_id") for x in r["results"]}
    assert "L1" in ids, "라이브 정책이 결과에 포함돼야 함(파묻힘 방지)"
    lives = [x for x in r["results"] if x["source"] == "live"]
    assert lives, "라이브 태그 결과가 있어야 함"
    assert all(x["eligibility_check"] == "manual" for x in lives)
    curated = [x for x in r["results"] if x["source"] == "curated"]
    assert curated, "코퍼스 결과도 함께 있어야 함"
    assert all(x["eligibility_check"] == "structured" for x in curated)
    # 요약 메타
    assert r["live_count"] == len(lives)
    assert r["curated_count"] == len(curated)
    assert r["total_available"] == 1234
    assert r["is_mock"] is False


async def test_live_dedupe_curated_priority(monkeypatch):
    """같은 정책명이 라이브에도 있으면 dedupe(큐레이션 우선) — 중복 노출 안 함."""
    # 코퍼스에 존재하는 '청년월세 특별지원'과 동일 이름을 라이브로 주입
    live_items = [
        {"policy_id": "DUP", "name": "청년월세 특별지원", "summary": "라이브 중복"},
        {"policy_id": "UNIQ", "name": "완전히 새로운 라이브 정책", "summary": "고유"},
    ]

    async def fake(*a, **k):
        return _live_result(live_items)

    monkeypatch.setattr(youthcenter, "search_policies", fake)
    r = await policies.search("KEY", "월세 지원", k=8)

    names = [x["name"] for x in r["results"]]
    # '청년월세 특별지원'은 정확히 1번(코퍼스 것)만 등장
    assert names.count("청년월세 특별지원") == 1
    dup_rows = [x for x in r["results"] if x["name"] == "청년월세 특별지원"]
    assert dup_rows[0]["source"] == "curated", "중복 시 큐레이션이 남아야 함"
    # 고유 라이브 정책은 포함
    assert "완전히 새로운 라이브 정책" in names


async def test_live_guaranteed_not_buried(monkeypatch):
    """코퍼스 hit 가 많아도 상위 k 안에 라이브가 최소 1개 이상 보장된다."""
    live_items = [
        {"policy_id": "LX", "name": "보장 라이브 정책", "summary": "보장"},
    ]

    async def fake(*a, **k):
        return _live_result(live_items)

    monkeypatch.setattr(youthcenter, "search_policies", fake)
    # 광범위 질의로 코퍼스 hit 를 많이 유도하고 k 를 작게
    r = await policies.search("KEY", "청년 지원", k=3)
    assert len(r["results"]) <= 3
    assert any(x["source"] == "live" for x in r["results"]), "라이브가 top-k 에 보장돼야 함"


def test_norm_name_dedupe_key():
    """정책명 정규화: 공백·괄호·구두점 제거 후 소문자."""
    assert policies._norm_name("청년 월세 (특별) 지원") == policies._norm_name("청년월세특별지원")
    assert policies._norm_name("K-패스 (청년)") == policies._norm_name("k패스청년")

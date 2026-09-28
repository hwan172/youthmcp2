"""내장 청년정책 코퍼스 BM25 검색 테스트 (네트워크 불필요)."""
from __future__ import annotations

from policy_mcp import policies, policy_corpus


def _ids(results: list[dict]) -> list[str]:
    return [r["policy_id"] for r in results]


def test_corpus_has_curated_policies():
    assert len(policy_corpus.POLICIES) >= 8
    # 모든 정책은 출처·기준일을 가진다(사실확인 원칙).
    for p in policy_corpus.POLICIES:
        assert p.source and p.as_of


def test_search_month_rent_returns_rent_policy():
    hits = policies.corpus_search("월세 지원", k=6)
    assert "youth-monthly-rent" in _ids(hits)
    assert _ids(hits)[0] == "youth-monthly-rent"  # 최상위


def test_search_asset_building():
    hits = policies.corpus_search("목돈 마련 자산형성 적금", k=6)
    ids = _ids(hits)
    assert any(i in ids for i in ("youth-leap-account", "youth-tomorrow-savings", "youth-future-savings"))


def test_search_jobseeker_allowance():
    hits = policies.corpus_search("구직 수당 취업 지원", k=6)
    ids = _ids(hits)
    assert any(i in ids for i in ("national-employment-support", "seoul-youth-allowance"))


def test_search_transit_discount():
    hits = policies.corpus_search("대중교통 교통비 환급 할인", k=6)
    ids = _ids(hits)
    assert any(i in ids for i in ("k-pass-youth", "climate-card-youth"))


def test_region_filter_excludes_seoul_only_for_busan():
    # 서울 전용 정책(청년수당)은 부산 필터에서 제외되어야 한다.
    hits = policies.corpus_search("청년수당 구직 지원금", region="부산", k=6)
    assert "seoul-youth-allowance" not in _ids(hits)


def test_region_filter_keeps_nationwide():
    # 전국 정책(월세)은 어떤 지역 필터에서도 남는다.
    hits = policies.corpus_search("월세 지원", region="부산", k=6)
    assert "youth-monthly-rent" in _ids(hits)


def test_results_carry_source_and_eligibility_summary():
    hits = policies.corpus_search("월세", k=3)
    assert hits
    for r in hits:
        assert r.get("source")
        assert "eligibility_summary" in r


def test_get_policy_and_detail():
    p = policy_corpus.get_policy("youth-monthly-rent")
    assert p is not None
    d = p.detail()
    assert d["policy_id"] == "youth-monthly-rent"
    assert d["apply_url"]
    assert "eligibility_summary" in d


def test_get_unknown_policy_is_none():
    assert policy_corpus.get_policy("does-not-exist") is None

"""자격 판정 엔진 테스트 — 각 verdict 경로 (네트워크 불필요)."""
from __future__ import annotations

from policy_mcp import policy_corpus
from policy_mcp.eligibility import (
    ELIGIBLE,
    INELIGIBLE,
    MANUAL_REVIEW,
    NEEDS_MORE_INFO,
    UserProfile,
    evaluate,
)


def _p(pid: str):
    p = policy_corpus.get_policy(pid)
    assert p is not None
    return p


# ── UserProfile 파싱 ──

def test_profile_from_dict_coerces_types_and_extra():
    prof = UserProfile.from_dict({"age": "27", "annual_income": "28000000",
                                  "region": "서울", "foo": "bar"})
    assert prof.age == 27
    assert prof.annual_income == 28_000_000
    assert prof.region == "서울"
    assert prof.extra == {"foo": "bar"}


def test_profile_from_dict_bad_numbers_become_none():
    prof = UserProfile.from_dict({"age": "몰라", "annual_income": ""})
    assert prof.age is None and prof.annual_income is None


def test_profile_from_none_is_all_empty():
    prof = UserProfile.from_dict(None)
    assert prof.age is None and prof.region is None


# ── verdict: ineligible ──

def test_age_over_limit_is_ineligible():
    # 청년월세: 만 19~34세. 40세 → 부적격 + 이유.
    res = evaluate(_p("youth-monthly-rent"), UserProfile(age=40, region="서울"))
    assert res["verdict"] == INELIGIBLE
    assert res["reasons_fail"]
    assert any("연령" in r or "범위" in r for r in res["reasons_fail"])


def test_income_over_cap_is_ineligible():
    # 청년 주택드림: 연소득 5,000만원 이하. 6,000만원 → 부적격.
    res = evaluate(_p("youth-housing-dream-account"),
                   UserProfile(age=30, annual_income=60_000_000))
    assert res["verdict"] == INELIGIBLE
    assert any("초과" in r for r in res["reasons_fail"])


def test_wrong_region_is_ineligible():
    # 서울 청년수당: 서울 거주 필요. 부산 → 부적격.
    res = evaluate(_p("seoul-youth-allowance"),
                   UserProfile(age=27, region="부산", employment_status="구직"))
    assert res["verdict"] == INELIGIBLE
    assert any("지역" in r for r in res["reasons_fail"])


def test_excluded_employment_is_ineligible():
    # 서울 청년수당: 재직/자영업 제외. 재직 → 부적격.
    res = evaluate(_p("seoul-youth-allowance"),
                   UserProfile(age=27, region="서울", employment_status="재직"))
    assert res["verdict"] == INELIGIBLE
    assert any("제외" in r for r in res["reasons_fail"])


# ── verdict: needs_more_info ──

def test_missing_age_is_needs_more_info():
    # 나이 정보 없음(다른 fail 없음) → 정보부족 + missing_info 질문.
    res = evaluate(_p("k-pass-youth"), UserProfile(region="서울"))
    assert res["verdict"] == NEEDS_MORE_INFO
    conds = [m["condition"] for m in res["missing_info"]]
    assert "age" in conds
    assert res["questions"]  # 후속 질문이 생성됨


def test_empty_profile_is_needs_more_info_with_questions():
    res = evaluate(_p("youth-monthly-rent"), UserProfile())
    assert res["verdict"] == NEEDS_MORE_INFO
    assert res["missing_info"]
    assert res["questions"]


def test_missing_income_when_age_ok_is_needs_more_info():
    # 나이는 통과, 소득 미상 → needs_more_info(income unknown).
    res = evaluate(_p("youth-housing-dream-account"), UserProfile(age=30))
    assert res["verdict"] == NEEDS_MORE_INFO
    conds = [m["condition"] for m in res["missing_info"]]
    assert "income" in conds


# ── verdict: manual_review ──

def test_all_structured_pass_leaves_manual_review():
    # K-패스: 구조화 조건은 나이뿐. 나이 통과 → 남은 건 정성(min_trips) → manual_review.
    res = evaluate(_p("k-pass-youth"), UserProfile(age=25))
    assert res["verdict"] == MANUAL_REVIEW
    assert res["manual_conditions"]
    assert any(c["condition"] == "min_trips" for c in res["manual_conditions"])


def test_seoul_allowance_full_profile_manual_review():
    # 서울 청년수당: 나이/지역/취업 통과 → 남은 가구소득 등 정성 → manual_review.
    res = evaluate(_p("seoul-youth-allowance"),
                   UserProfile(age=27, region="서울", employment_status="구직"))
    assert res["verdict"] == MANUAL_REVIEW
    # 구조화 조건은 모두 pass
    statuses = {c["condition"]: c["status"] for c in res["checks"]}
    assert statuses["age"] == "pass"
    assert statuses["region"] == "pass"
    assert statuses["employment"] == "pass"


# ── verdict: eligible (정성 조건 없는 정책) ──

def test_eligible_when_no_manual_and_all_pass():
    # 정성 조건 0개인 가짜 정책을 구성해 순수 eligible 경로 검증.
    from policy_mcp.policy_corpus import Policy
    p = Policy(id="tmp", name="임시", category="c", subcategory="s",
               summary="", support_content="", blurb="", source="src", as_of="2026-07",
               age_min=19, age_max=34, income_max_won=50_000_000, regions=["서울"])
    res = evaluate(p, UserProfile(age=27, region="서울", annual_income=30_000_000))
    assert res["verdict"] == ELIGIBLE
    assert not res["reasons_fail"]
    assert not res["missing_info"]


# ── 판정 상세/구조 ──

def test_checks_include_pass_detail_and_source():
    res = evaluate(_p("youth-monthly-rent"), UserProfile(age=25))
    age_check = next(c for c in res["checks"] if c["condition"] == "age")
    assert age_check["status"] == "pass"
    assert res["source"] and res["as_of"]


def test_region_partial_match_seoul_special_city():
    # "서울특별시"로 저장돼 있어도 "서울" 정책 지역과 부분일치로 통과해야 한다.
    res = evaluate(_p("seoul-youth-allowance"),
                   UserProfile(age=27, region="서울특별시 강남구", employment_status="구직"))
    region_check = next(c for c in res["checks"] if c["condition"] == "region")
    assert region_check["status"] == "pass"

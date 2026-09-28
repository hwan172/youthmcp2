"""자격 판정 엔진 (킬러 기능) — 순수 함수, 결정론적.

정책의 구조화 조건(연령/지역/소득/취업상태) 을 사용자 프로필과 대조해 조건별로 판정한다:
  - pass        : 조건 충족
  - fail        : 조건 불충족(이유 포함) → 종합적으로 부적격 근거
  - unknown     : 프로필에 해당 정보가 없어 판정 불가 → missing_info 에 '무엇을 물어야 하는지' 수록
  - manual      : 자유텍스트(정성) 조건 → 호스트 LLM/공고 확인에 원문 전달

종합 verdict:
  - ineligible      : fail 이 하나라도 있음(확정 부적격)
  - needs_more_info : fail 없음 + unknown/manual 존재(추가 정보/공고 확인 필요) → 후속 질문 유도
  - eligible        : 판정 가능한 모든 조건 pass + unknown/manual 없음
  (manual 만 남고 unknown 없으면 needs_more_info(manual_review 성격) — questions 는 manual 조건 확인 요청)

에이전틱 루프 핵심: needs_more_info 의 missing_info(questions) 가 호스트의 후속 질문을 유도한다.
호스트는 사용자에게 되묻고, 답을 remember_user_profile 로 저장한 뒤 check_eligibility 를 재호출한다.

이 모듈은 네트워크·상태 없음. server 와 무관하게 단위테스트 가능.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .policy_corpus import Policy

# 판정 상태
PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"
MANUAL = "manual"

# 종합 verdict
ELIGIBLE = "eligible"
INELIGIBLE = "ineligible"
NEEDS_MORE_INFO = "needs_more_info"
MANUAL_REVIEW = "manual_review"


@dataclass
class UserProfile:
    """사용자 상황. 전부 Optional — 아는 것만 채운다(모르면 unknown 판정)."""
    age: Optional[int] = None
    region: Optional[str] = None            # 거주 시도/시군구 문자열(예: "서울", "경기 성남시")
    annual_income: Optional[int] = None     # 개인 연소득(원)
    income_band: Optional[str] = None       # 소득 구간 문자열(연소득 미상 시 보조)
    employment_status: Optional[str] = None  # 재직/구직/자영업/학생/무직 등
    education: Optional[str] = None
    marital_status: Optional[str] = None
    extra: dict = field(default_factory=dict)  # 기타 자유 항목(가구소득 등 정성 조건 힌트)

    @staticmethod
    def from_dict(d: Optional[dict]) -> "UserProfile":
        d = d or {}
        known = {"age", "region", "annual_income", "income_band",
                 "employment_status", "education", "marital_status"}
        extra = {k: v for k, v in d.items() if k not in known}
        age = d.get("age")
        try:
            age = int(age) if age is not None and str(age).strip() != "" else None
        except (ValueError, TypeError):
            age = None
        income = d.get("annual_income")
        try:
            income = int(income) if income is not None and str(income).strip() != "" else None
        except (ValueError, TypeError):
            income = None
        return UserProfile(
            age=age,
            region=(d.get("region") or None),
            annual_income=income,
            income_band=(d.get("income_band") or None),
            employment_status=(d.get("employment_status") or None),
            education=(d.get("education") or None),
            marital_status=(d.get("marital_status") or None),
            extra=extra,
        )


@dataclass
class Check:
    """조건 하나에 대한 판정 결과."""
    condition: str          # 조건 이름(age/region/income/employment/<criterion.key>)
    status: str             # PASS/FAIL/UNKNOWN/MANUAL
    detail: str             # 사람이 읽는 설명(이유)
    ask: str = ""           # unknown/manual 일 때 사용자에게 되물을 질문


def _region_matches(profile_region: str, allowed: list[str]) -> bool:
    """거주지 매칭: 정책 허용 시도명이 프로필 지역 문자열에 포함되면 통과(부분일치)."""
    pr = profile_region.replace(" ", "")
    for a in allowed:
        a2 = a.replace(" ", "")
        if a2 and (a2 in pr or pr in a2):
            return True
    return False


def evaluate(policy: Policy, profile: UserProfile) -> dict:
    """정책 vs 프로필 자격 판정. 결정론적."""
    checks: list[Check] = []

    # ── 연령 ──
    if policy.age_min is not None or policy.age_max is not None:
        lo, hi = policy.age_min, policy.age_max
        rng = f"만 {lo if lo is not None else '-'}~{hi if hi is not None else '-'}세"
        if profile.age is None:
            checks.append(Check("age", UNKNOWN, f"연령 조건({rng})이 있으나 나이 정보가 없습니다.",
                                "나이(만 나이)가 어떻게 되나요?"))
        else:
            below = lo is not None and profile.age < lo
            above = hi is not None and profile.age > hi
            if below or above:
                checks.append(Check("age", FAIL,
                                    f"나이 {profile.age}세가 대상 연령({rng}) 범위를 벗어납니다."))
            else:
                checks.append(Check("age", PASS, f"나이 {profile.age}세가 대상 연령({rng})에 해당합니다."))

    # ── 지역 ──
    if policy.regions:
        allowed = "·".join(dict.fromkeys(policy.regions))
        if profile.region is None:
            checks.append(Check("region", UNKNOWN,
                                f"거주지 조건({allowed})이 있으나 지역 정보가 없습니다.",
                                "현재 거주(주민등록) 지역이 어디인가요?"))
        elif _region_matches(profile.region, policy.regions):
            checks.append(Check("region", PASS, f"거주지 '{profile.region}'가 대상 지역({allowed})에 해당합니다."))
        else:
            checks.append(Check("region", FAIL,
                                f"거주지 '{profile.region}'가 대상 지역({allowed})이 아닙니다."))

    # ── 소득(개인 연소득 상한) ──
    if policy.income_max_won is not None:
        cap = policy.income_max_won
        if profile.annual_income is None:
            checks.append(Check("income", UNKNOWN,
                                f"개인 연소득 상한({cap:,}원)이 있으나 소득 정보가 없습니다.",
                                "본인의 연소득(세전, 원)이 대략 얼마인가요?"))
        elif profile.annual_income <= cap:
            checks.append(Check("income", PASS,
                                f"연소득 {profile.annual_income:,}원이 상한({cap:,}원) 이하입니다."))
        else:
            checks.append(Check("income", FAIL,
                                f"연소득 {profile.annual_income:,}원이 상한({cap:,}원)을 초과합니다."))

    # ── 취업상태 ──
    if policy.employment_in or policy.employment_not:
        if profile.employment_status is None:
            need = ""
            if policy.employment_in:
                need = f"허용: {', '.join(policy.employment_in)}"
            if policy.employment_not:
                need = (need + " / " if need else "") + f"제외: {', '.join(policy.employment_not)}"
            checks.append(Check("employment", UNKNOWN,
                                f"취업상태 조건({need})이 있으나 취업상태 정보가 없습니다.",
                                "현재 취업상태가 어떻게 되나요? (재직/구직/자영업/학생/무직 등)"))
        else:
            es = profile.employment_status
            if policy.employment_not and es in policy.employment_not:
                checks.append(Check("employment", FAIL,
                                    f"취업상태 '{es}'는 이 정책 대상에서 제외됩니다."))
            elif policy.employment_in and es not in policy.employment_in:
                checks.append(Check("employment", FAIL,
                                    f"취업상태 '{es}'는 대상({', '.join(policy.employment_in)})에 해당하지 않습니다."))
            else:
                checks.append(Check("employment", PASS, f"취업상태 '{es}'가 대상 조건에 부합합니다."))

    # ── 정성(자유텍스트) 조건 → manual ──
    for c in policy.criteria:
        checks.append(Check(c.key, MANUAL, c.text, c.ask))

    # ── 종합 verdict ──
    fails = [c for c in checks if c.status == FAIL]
    unknowns = [c for c in checks if c.status == UNKNOWN]
    manuals = [c for c in checks if c.status == MANUAL]

    if fails:
        verdict = INELIGIBLE
    elif unknowns:
        verdict = NEEDS_MORE_INFO
    elif manuals:
        # 구조화 조건은 모두 통과, 남은 건 공고 확인성 정성 조건뿐.
        verdict = MANUAL_REVIEW
    else:
        verdict = ELIGIBLE

    # 후속 질문(missing_info): unknown(정보 없음) + manual(정성 확인) 의 ask 를 모은다.
    questions = [c.ask for c in unknowns if c.ask] + [c.ask for c in manuals if c.ask]

    return {
        "policy_id": policy.id,
        "policy_name": policy.name,
        "verdict": verdict,
        "checks": [
            {"condition": c.condition, "status": c.status, "detail": c.detail,
             **({"ask": c.ask} if c.ask else {})}
            for c in checks
        ],
        "reasons_fail": [c.detail for c in fails],
        "missing_info": [
            {"condition": c.condition, "question": c.ask}
            for c in unknowns if c.ask
        ],
        "manual_conditions": [
            {"condition": c.condition, "detail": c.detail,
             **({"question": c.ask} if c.ask else {})}
            for c in manuals
        ],
        "questions": questions,
        "source": policy.source,
        "as_of": policy.as_of,
        "note": _verdict_note(verdict),
    }


def _verdict_note(verdict: str) -> str:
    if verdict == ELIGIBLE:
        return ("판정 가능한 모든 조건을 충족합니다(eligible). 정성 조건이 없어도 최종 확정은 "
                "공고·서류 심사를 따릅니다. 신청 방법은 get_policy_detail 을 참고하세요.")
    if verdict == INELIGIBLE:
        return ("하나 이상의 조건에서 부적격입니다(ineligible). reasons_fail 의 사유를 사용자에게 "
                "설명하세요. 프로필이 바뀌면(예: 이사·소득변동) 재판정하세요.")
    if verdict == NEEDS_MORE_INFO:
        return ("확정 부적격 사유는 없으나 판정에 필요한 정보가 부족합니다(needs_more_info). "
                "questions 로 사용자에게 되묻고, 답을 remember_user_profile 로 저장한 뒤 "
                "check_eligibility 를 다시 호출하세요. 이것이 개인화 판정 루프입니다.")
    # MANUAL_REVIEW
    return ("구조화 조건은 모두 통과했고, 남은 것은 공고·서류로 확인할 정성 조건뿐입니다"
            "(manual_review). manual_conditions 를 사용자에게 안내하고 최신 공고(apply_url)를 "
            "확인하도록 하세요.")

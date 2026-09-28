"""Youth Policy Navigator — 카카오 PlayMCP 공모전용 MCP 서버.

핵심 원칙: 서버는 '데이터 + 결정론적 판정 도구'만 제공한다.
자연어 해석과 최종 안내 문구는 호스트 LLM(PlayMCP AI / Claude)이 담당한다.

차별점: 단순 정책 조회를 넘어, 사용자 프로필 대비 자격을 조건별로 판정(적격/부적격/정보부족)해
'이유'와 '되물어야 할 질문(missing_info)'을 반환한다 → 호스트의 후속 질문·개인화 루프를 유도.

PlayMCP 규약 준수: Streamable HTTP, 툴 5개, name/description/inputSchema/annotations 완비,
description 은 영문 + 서비스명(영/국 병기) 포함, 1024자 이내, 툴명 [A-Za-z0-9_-]·'kakao' 금지.

실행:
  - 로컬(stdio, MCP Inspector용):   uv run policy-mcp
  - 원격(http, PlayMCP 등록용):     MCP_TRANSPORT=http uv run policy-mcp
"""
from __future__ import annotations

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import memory, policies, policy_corpus
from .clients import youthcenter_centers
from .config import settings
from .eligibility import UserProfile, evaluate

mcp = FastMCP(name="Youth Policy Navigator")

# 데이터를 읽기만 하는 툴(부작용 없음) → read-only/non-destructive/idempotent/open-world.
_READONLY = dict(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
# 사용자 프로필을 기록하는 툴(상태 변경, 비파괴) → 로컬 저장이라 open-world 아님.
_MUTATING = dict(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)


@mcp.tool(
    description=(
        "Youth Policy Navigator(청년 정책 내비게이터): search Korean youth policies and subsidies "
        "(housing rent support, asset-building savings, job-seeker allowances, transit discounts, "
        "housing subscription accounts, etc.) by free-text query, optional region and category. Fuses a "
        "curated built-in corpus of representative 2026 policies with the 온통청년 (Youth Center) open "
        "API when a key is configured. Call this when the user asks what youth policies or support money "
        "they could get, or searches by topic (e.g. '월세 지원', '취업 수당', '목돈 마련'). Each result "
        "includes a summary and STRUCTURED eligibility criteria; then call check_eligibility with a "
        "policy_id to judge whether the user actually qualifies."
    ),
    annotations=ToolAnnotations(title="Search youth policies", **_READONLY),
)
async def search_youth_policies(
    query: str,
    region: str | None = None,
    category: str | None = None,
    k: int = 6,
) -> dict:
    """청년정책·지원금 검색(내장 코퍼스 BM25 + 키 있으면 온통청년 API 융합). ★진입점.

    query: 자연어 질의(예: '월세 지원', '자산형성 목돈', '구직 수당').
    region: 거주 시도명으로 필터(예: '서울'). category: 대/중분류 키워드(예: '주거','금융').
    각 result 는 구조화 자격조건 포함 → policy_id 로 check_eligibility 판정.
    """
    return await policies.search(settings.youthcenter_policy_key, query, region, category, k)


@mcp.tool(
    description=(
        "Youth Policy Navigator(청년 정책 내비게이터): the KILLER feature — deterministically judge "
        "whether a user is eligible for a specific policy (by policy_id). Provide the user's situation "
        "either inline via profile (age, region, annual_income, income_band, employment_status, "
        "education, marital_status — all optional) or via user_key to restore a remembered profile. "
        "Returns a verdict (eligible / ineligible / needs_more_info / manual_review) with per-condition "
        "checks, fail reasons, and — crucially — missing_info questions to ASK the user next when data is "
        "insufficient. Use those questions to drive a follow-up loop: ask, save with "
        "remember_user_profile, then re-run this. Free-text conditions are returned as manual for you to "
        "confirm against the notice."
    ),
    annotations=ToolAnnotations(title="Check policy eligibility", **_READONLY),
)
async def check_eligibility(
    policy_id: str,
    user_key: str | None = None,
    profile: dict | None = None,
) -> dict:
    """★킬러 기능: 정책 조건 vs 사용자 프로필 자격 판정(적격/부적격/정보부족/공고확인).

    policy_id: search_youth_policies 결과의 정책 ID.
    profile: {age, region, annual_income, income_band, employment_status, education, marital_status}
             (전부 Optional — 아는 것만). 또는 user_key 로 저장된 프로필 복원.
    반환의 missing_info(questions) 로 사용자에게 되묻고, 답을 remember_user_profile 로 저장 후 재호출.
    """
    p = policy_corpus.get_policy(policy_id)
    if p is None:
        return {"error": "policy_not_found",
                "message": f"'{policy_id}' 정책을 찾지 못했습니다. search_youth_policies 로 먼저 검색하세요.",
                "hint": "policy_id 는 내장 코퍼스 정책에 대해서만 구조화 판정이 가능합니다."}

    prof = UserProfile.from_dict(profile)
    memory_notes: list[str] = []
    if user_key and profile is None:
        # 프로필 직접 전달이 없으면 메모리 노트를 참고자료로 첨부(구조화 파싱은 호스트가).
        memory_notes = memory.recall_notes(user_key, query=p.name, k=10)

    result = evaluate(p, prof)
    if memory_notes:
        result["memory_notes"] = memory_notes
        result["note"] = (result["note"] + " (참고: user_key 의 저장 노트를 memory_notes 로 첨부했습니다. "
                          "이 노트에서 나이·지역·소득 등을 추출해 profile 로 재호출하면 더 정확히 판정됩니다.)")
    return result


@mcp.tool(
    description=(
        "Youth Policy Navigator(청년 정책 내비게이터): return full application details for a specific "
        "policy (by policy_id) — support content, application period, how to apply, required documents, "
        "official apply URL, supervising agency, and an eligibility summary with source and as-of date. "
        "Call this after the user picks a policy from search_youth_policies and wants to know how and when "
        "to apply, or what documents are needed."
    ),
    annotations=ToolAnnotations(title="Get policy detail", **_READONLY),
)
async def get_policy_detail(policy_id: str) -> dict:
    """정책 상세: 지원내용·신청기간·신청방법·서류·URL·주관기관·출처."""
    p = policy_corpus.get_policy(policy_id)
    if p is None:
        return {"error": "policy_not_found",
                "message": f"'{policy_id}' 정책을 찾지 못했습니다. search_youth_policies 로 먼저 검색하세요."}
    return p.detail()


@mcp.tool(
    description=(
        "Youth Policy Navigator(청년 정책 내비게이터): remember a user's situation or preference for "
        "later personalization and eligibility judging (e.g. '나이 27', '서울 거주', '연소득 2800만원', "
        "'구직 중', '대학 졸업'). Pass a stable per-user identifier as user_key that YOU control, and a "
        "short note. Call this whenever the user reveals a durable fact about their age, region, income, "
        "employment or education, so a later check_eligibility can restore and use it."
    ),
    annotations=ToolAnnotations(title="Remember user profile", **_MUTATING),
)
async def remember_user_profile(user_key: str, note: str) -> dict:
    """사용자 상황/선호 저장(개인화·자격판정용). user_key 는 호스트가 관리하는 사용자 식별자."""
    return memory.save(user_key, note)


@mcp.tool(
    description=(
        "Youth Policy Navigator(청년 정책 내비게이터): recall a user's previously saved situation/"
        "preferences relevant to a query, via contextual retrieval. Pass the same user_key used when "
        "saving. Call this before recommending policies or judging eligibility to personalize; an empty "
        "query returns the most recent notes."
    ),
    annotations=ToolAnnotations(title="Recall user profile", **_READONLY),
)
async def recall_user_profile(user_key: str, query: str = "", k: int = 6) -> dict:
    """저장된 사용자 상황/선호 회상(개인화). 추천·판정 전에 호출해 반영."""
    return memory.recall(user_key, query, k)


@mcp.tool(
    description=(
        "Youth Policy Navigator(청년 정책 내비게이터): find nearby Korean youth centers (청년센터/"
        "청년공간) for offline, in-person help — connecting a user to a local place where staff can "
        "walk them through applications and documents AFTER policies are matched. Filter by region "
        "(시도/시군구 name, e.g. '서울', '경기 수원') and/or a free-text keyword (center name or area). "
        "Returns each center's name, address, phone, homepage URL, and 시도/시군구. Backed by the "
        "온통청년 (Youth Center) getSpace open API (about 678 centers nationwide) when a key is "
        "configured; region and keyword filtering are applied client-side. Call this once the user "
        "wants face-to-face guidance or asks where they can get help near them."
    ),
    annotations=ToolAnnotations(title="Find youth centers", **_READONLY),
)
async def find_youth_centers(
    region: str | None = None,
    keyword: str | None = None,
    limit: int = 8,
) -> dict:
    """전국 청년센터 검색(온통청년 getSpace). 정책 매칭 후 오프라인 상담 연결용.

    region: 시도/시군구명 부분일치(예: '서울', '경기 수원'). keyword: 센터명/지역 자유 검색.
    반환: 센터 목록(이름·주소·전화·홈페이지·시도/시군구) + note. 키 미설정 시 mock 폴백(is_mock=True).
    """
    return await youthcenter_centers.search_centers(
        settings.youthcenter_centers_key, region=region, keyword=keyword, limit=limit)


def main() -> None:
    if settings.transport == "http":
        # PlayMCP 등록용 원격 엔드포인트: http://{host}:{port}/mcp
        mcp.run(transport="http", host=settings.host, port=settings.port)
    else:
        mcp.run()  # 로컬 개발 / MCP Inspector


if __name__ == "__main__":
    main()

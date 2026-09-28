"""온통청년(youthcenter.go.kr) 청년정책 OPEN API 클라이언트 (한국고용정보원 / 공공데이터포털 15143273).

✅ 라이브 검증 완료 (2026-07, 실제 발급키로 httpx 호출 대조).
  - 엔드포인트 : GET https://www.youthcenter.go.kr/go/ythip/getPlcy
  - 인증       : 쿼리파라미터 apiKeyNm=<키>  (구 API 의 openApiVlak 아님)
  - 응답 포맷  : rtnType=json 지정 시 JSON. 래핑 = result.youthPolicyList[], 건수 = result.pagging.totCount
  - 검색       : plcyNm=<질의>  (정책명 부분일치. plcyKywdNm 은 '보조금' 같은 통제 태그라 자유질의엔 부적합)
  - 분류필터   : lclsfNm=<대분류명>  (예: '주거','일자리','금융･복지･문화')
  - 페이지네이션: pageNum / pageSize
  - 지역필터   : API 는 zipCd(법정동코드) 만 받고 시도명 필터는 없음 → 지역 필터는 코퍼스 융합 단계에서 처리.
  - 아래 _map_item() 필드명은 실제 응답 필드를 1순위로, 방어적 폴백을 2순위로 둔다.

정직성 원칙(기존 레포 계승): 키가 없거나 호출이 실패하면 조용히 가짜 데이터를 흘리지 않는다.
내장 코퍼스를 mock 폴백으로 쓰되 응답에 is_mock=True 와 note 로 명시한다.
"""
from __future__ import annotations

import httpx

from .. import cache
from ..policy_corpus import POLICIES, Policy
from ..retrieval import bm25_search

# 2025 개편 신규 API(JSON 지원). 라이브 검증 완료(위 주석 참조).
_ENDPOINT = "https://www.youthcenter.go.kr/go/ythip/getPlcy"
_TIMEOUT = 3.0        # p99 예산: 온통청년 정상응답 <1s, 여유 포함 3s 컷(초과 시 mock 폴백)
_CACHE_TTL = 300.0    # 라이브 성공 결과만 5분 캐시


def _map_item(item: dict) -> dict:
    """API 응답 아이템 → 내부 표준 dict. 실제 필드명 1순위 + 방어적 폴백."""
    def g(*keys: str) -> str:
        for k in keys:
            v = item.get(k)
            if v is not None and str(v).strip() != "":  # 공백-only('       ') 도 미설정 취급
                return str(v).strip()
        return ""

    def gi(*keys: str):
        v = g(*keys)
        try:
            return int(v) if v != "" else None
        except ValueError:
            return None

    # 신청/사업 기간: aplyYmd(신청기간) → 사업기간(bizPrdBgngYmd~EndYmd) → bizPrdEtcCn('연중' 등)
    period = g("aplyYmd", "bizPrdCn")
    if not period:
        bgn, end = g("bizPrdBgngYmd"), g("bizPrdEndYmd")
        if bgn or end:
            period = f"{bgn} ~ {end}".strip(" ~")
    if not period:
        period = g("bizPrdEtcCn")

    return {
        "policy_id": g("plcyNo", "bizId", "polyBizSecd"),
        "name": g("plcyNm", "polyBizSttus"),
        "summary": g("plcyExplnCn", "polyItcnCn"),
        "support_content": g("plcySprtCn", "sporCn"),
        "category": g("lclsfNm", "polyBizTy"),
        "subcategory": g("mclsfNm"),
        "keyword": g("plcyKywdNm"),
        "age_min": gi("sprtTrgtMinAge", "ageInfo"),
        "age_max": gi("sprtTrgtMaxAge"),
        "age_limited": g("sprtTrgtAgeLmtYn"),  # 'Y'=연령제한 있음 / 'N'=제한 없음
        "income_note": g("earnEtcCn", "earnCndSeCd", "earnCn"),
        "income_min": gi("earnMinAmt"),
        "income_max": gi("earnMaxAmt"),
        "region_code": g("zipCd", "polyRlmCd"),  # 콤마구분 법정동코드
        "employment_text": g("jobCd", "empmSttsCn"),
        "education_text": g("schoolCd", "accrRqisCn"),
        "marital_text": g("mrgSttsCd"),
        "extra_qualification": g("addAplyQlfcCndCn", "ptcpPrpTrgtCn", "etct"),
        "apply_method": g("plcyAplyMthdCn"),
        "documents": g("sbmsnDcmntCn"),
        "apply_url": g("aplyUrlAddr", "refUrlAddr1", "refUrlAddr2"),
        "ref_url": g("refUrlAddr1", "refUrlAddr2"),
        "apply_period": period,
        "agency": g("sprvsnInstCdNm", "operInstCdNm", "rgtrInstCdNm"),
    }


def _mock_search(query: str | None, region: str | None, category: str | None, page_size: int) -> dict:
    """내장 코퍼스 기반 mock. 키 없음/호출 실패 시 폴백. is_mock=True 명시."""
    pool: list[Policy] = POLICIES
    if region:
        r = region.replace(" ", "")
        pool = [p for p in pool if (not p.regions) or any(r in x.replace(" ", "") or x.replace(" ", "") in r for x in p.regions)]
    if category:
        pool = [p for p in pool if category in p.category or category in p.subcategory]

    if query and query.strip():
        hits = bm25_search(query, [p.to_chunk() for p in pool], k=page_size)
        by_id = {p.id: p for p in pool}
        items = [{**by_id[c.id].detail(), "score": s} for s, c in hits if c.id in by_id]
    else:
        items = [p.detail() for p in pool[:page_size]]

    return {
        "items": items,
        "count": len(items),
        "is_mock": True,
        "source": "내장 청년정책 코퍼스 (온통청년 API 키 미설정 → mock 폴백)",
        "note": ("YOUTHCENTER_API_KEY_POLICY 미설정 또는 API 호출 실패로 내장 코퍼스로 응답했습니다. "
                 "라이브 데이터가 아니며, 정책 목록은 큐레이션된 대표 정책으로 제한됩니다."),
    }


async def search_policies(
    key: str | None,
    *,
    query: str | None = None,
    category: str | None = None,
    region: str | None = None,
    page_num: int = 1,
    page_size: int = 6,
) -> dict:
    """청년정책 검색. 키 None 이면 즉시 mock 폴백. 호출 실패 시에도 mock 으로 폴백(명시)."""
    if not key:
        return _mock_search(query, region, category, page_size)

    ck = ("youthcenter", query, category, region, page_num, page_size)
    cached = cache.get(ck, _CACHE_TTL)
    if cached is not None:
        return cached

    params: dict[str, str | int] = {
        "apiKeyNm": key,          # 인증: 쿼리파라미터 apiKeyNm (라이브 검증 완료)
        "pageNum": page_num,
        "pageSize": page_size,
        "rtnType": "json",
    }
    if query:
        params["plcyNm"] = query   # 정책명 부분일치 검색(자유질의). plcyKywdNm 은 통제 태그라 부적합.
    if category:
        params["lclsfNm"] = category  # 대분류명 필터(예: 주거/일자리/금융･복지･문화)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(_ENDPOINT, params=params)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        fallback = _mock_search(query, region, category, page_size)
        fallback["note"] = (f"온통청년 API 호출 실패({type(e).__name__}) → 내장 코퍼스로 폴백. "
                            "네트워크/키/필드 매핑을 확인하세요.")
        fallback["api_error"] = str(e)
        return fallback

    # 응답 구조(result.youthPolicyList 등)는 라이브 검증 후 확정 — 방어적으로 탐색.
    raw_items = _extract_items(data)
    items = [_map_item(it) for it in raw_items]
    result = {
        "items": items,
        "count": len(items),
        "total_count": _extract_total(data),  # result.pagging.totCount(질의 전체 매칭 건수)
        "is_mock": False,
        "source": "온통청년 청년정책 API (한국고용정보원, 공공데이터포털 15143273)",
        "note": "라이브 API 응답입니다. 필드 매핑은 clients/youthcenter.py 에서 관리합니다.",
    }
    if items:  # 성공 결과만 캐시
        cache.set(ck, result)
    return result


def _extract_total(data) -> int | None:
    """result.pagging.totCount(질의에 매칭되는 전체 건수)를 방어적으로 추출한다."""
    if isinstance(data, dict):
        res = data.get("result")
        if isinstance(res, dict):
            pag = res.get("pagging") or res.get("paging")
            if isinstance(pag, dict):
                try:
                    return int(pag.get("totCount"))
                except (TypeError, ValueError):
                    return None
    return None


def _extract_items(data) -> list[dict]:
    """다양한 응답 래핑에서 정책 리스트를 방어적으로 추출한다."""
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []
    # 흔한 래핑 후보들을 순서대로 시도.
    for path in (("result", "youthPolicyList"), ("result", "plcyLst"),
                 ("youthPolicyList",), ("plcyLst",), ("data",), ("items",)):
        node = data
        ok = True
        for key in path:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                ok = False
                break
        if ok:
            if isinstance(node, list):
                return [x for x in node if isinstance(x, dict)]
            if isinstance(node, dict):
                return [node]
    return []

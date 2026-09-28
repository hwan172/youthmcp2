"""온통청년(youthcenter.go.kr) 청년센터·청년공간 OPEN API 클라이언트 (getSpace).

✅ 라이브 검증 완료 (2026-07, 실제 발급키로 httpx 호출 대조).
  - 엔드포인트 : GET https://www.youthcenter.go.kr/go/ythip/getSpace
  - 인증       : 쿼리파라미터 apiKeyNm=<키>  (getPlcy 와 동일 방식)
  - 응답 포맷  : rtnType=json 지정 시 JSON. 래핑 = result.youthPolicyList[](주의: 정책 API 와 키 동일),
                건수 = result.pagging.totCount(전국 청년센터 678건).
  - 실제 필드 : cntrSn(일련), cntrNm(센터명), cntrAddr(주소), cntrDaddr(상세주소),
                cntrTelno(전화), cntrUrlAddr(홈페이지), stdgCtpvCd(Nm)(시도), stdgSggCd(Nm)(시군구).
  - 지역/키워드: API 는 서버측 region/keyword 파라미터를 지원하지 않는다(라이브 검증: 어떤 값을 줘도
                전체 리스트 반환). → 지역·키워드 필터는 전체를 받아 클라이언트단에서 처리한다.

정직성 원칙(레포 계승): 키가 없거나 호출 실패 시 조용히 가짜 데이터를 흘리지 않는다.
소수의 내장 대표 센터를 mock 폴백으로 쓰되 is_mock=True + note 로 명시한다.
"""
from __future__ import annotations

import httpx

from .. import cache
from .youthcenter import _extract_items, _extract_total

_ENDPOINT = "https://www.youthcenter.go.kr/go/ythip/getSpace"
_TIMEOUT = 3.0          # p99 예산: 정상응답 <1s, 여유 포함 3s 컷(초과 시 mock 폴백)
_CACHE_TTL = 300.0      # 라이브 성공 결과만 5분 캐시
_FETCH_MAX = 700        # 지역/키워드 필터 시 전체(678건)를 받아 클라이언트단 필터


def _map_center(item: dict) -> dict:
    """getSpace 응답 아이템 → 내부 표준 dict. 실제 필드명 1순위 + 방어적 폴백."""
    def g(*keys: str) -> str:
        for k in keys:
            v = item.get(k)
            if v is not None and str(v).strip() != "":
                return str(v).strip()
        return ""

    addr = g("cntrAddr")
    daddr = g("cntrDaddr")
    full_addr = f"{addr} {daddr}".strip() if daddr else addr
    return {
        "center_id": g("cntrSn"),
        "name": g("cntrNm"),
        "address": full_addr,
        "tel": g("cntrTelno"),
        "url": g("cntrUrlAddr"),
        "sido": g("stdgCtpvCdNm"),
        "sigungu": g("stdgSggCdNm"),
    }


# 내장 대표 청년센터(mock 폴백 전용, is_mock=True 로 명시). 라이브 응답에서 발췌한 실제 센터.
MOCK_CENTERS: list[dict] = [
    {"center_id": "m-seoul-mapo", "name": "서울청년센터 마포", "address": "서울특별시 마포구 월드컵로1길 14",
     "tel": "02-336-3690", "url": "https://youth.seoul.go.kr", "sido": "서울특별시", "sigungu": "마포구"},
    {"center_id": "m-seoul-seongbuk", "name": "서울청년센터 성북", "address": "서울특별시 성북구 종암로5길 7",
     "tel": "02-921-5330", "url": "https://youth.seoul.go.kr", "sido": "서울특별시", "sigungu": "성북구"},
    {"center_id": "m-busan", "name": "부산청년센터", "address": "부산광역시 부산진구 중앙대로",
     "tel": "051-711-0403", "url": "https://young.busan.go.kr", "sido": "부산광역시", "sigungu": "부산진구"},
    {"center_id": "m-gyeonggi", "name": "경기도 청년지원사업단", "address": "경기도 수원시 팔달구",
     "tel": "031-267-9280", "url": "https://youth.gg.go.kr", "sido": "경기도", "sigungu": "수원시"},
]


def _region_match(region: str, item: dict) -> bool:
    """거주 시도/시군구 부분일치: 시도명·시군구명·주소 중 하나라도 매칭되면 통과."""
    r = region.replace(" ", "")
    if not r:
        return True
    for field in (item.get("sido", ""), item.get("sigungu", ""), item.get("address", "")):
        f = field.replace(" ", "")
        if f and (r in f or f in r):
            return True
    return False


def _keyword_match(keyword: str, item: dict) -> bool:
    """키워드 부분일치: 센터명·주소·시군구명 중 하나라도 포함되면 통과."""
    kw = keyword.replace(" ", "").lower()
    if not kw:
        return True
    for field in (item.get("name", ""), item.get("address", ""), item.get("sigungu", "")):
        if kw in field.replace(" ", "").lower():
            return True
    return False


def _filter(items: list[dict], region: str | None, keyword: str | None) -> list[dict]:
    out = items
    if region:
        out = [it for it in out if _region_match(region, it)]
    if keyword:
        out = [it for it in out if _keyword_match(keyword, it)]
    return out


def _mock_centers(region: str | None, keyword: str | None, limit: int) -> dict:
    """내장 대표 센터 기반 mock. 키 없음/호출 실패 시 폴백. is_mock=True 명시."""
    items = _filter(MOCK_CENTERS, region, keyword)[:limit]
    return {
        "items": items,
        "count": len(items),
        "total_count": None,
        "is_mock": True,
        "source": "내장 대표 청년센터 (온통청년 getSpace 키 미설정 → mock 폴백)",
        "note": ("YOUTHCENTER_API_KEY_CENTERS 미설정 또는 API 호출 실패로 내장 대표 센터로 응답했습니다. "
                 "라이브 데이터가 아니며, 전국 청년센터 전체(약 678곳)가 아닌 일부 예시로 제한됩니다."),
    }


async def search_centers(
    key: str | None,
    *,
    region: str | None = None,
    keyword: str | None = None,
    limit: int = 8,
) -> dict:
    """청년센터 검색(getSpace). 키 None 이면 mock 폴백. 실패 시에도 mock 폴백(명시).

    지역/키워드 필터는 API 가 서버측 파라미터를 지원하지 않으므로 전체를 받아 클라이언트단에서 처리한다.
    """
    limit = max(1, min(int(limit or 8), 50))
    if not key:
        return _mock_centers(region, keyword, limit)

    filtering = bool(region or keyword)
    page_size = _FETCH_MAX if filtering else limit

    ck = ("youthcenter_centers", page_size)
    cached = cache.get(ck, _CACHE_TTL)
    if cached is not None:
        mapped, total = cached
    else:
        params: dict[str, str | int] = {
            "apiKeyNm": key,
            "pageNum": 1,
            "pageSize": page_size,
            "rtnType": "json",
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(_ENDPOINT, params=params)
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            fb = _mock_centers(region, keyword, limit)
            fb["note"] = (f"온통청년 getSpace 호출 실패({type(e).__name__}) → 내장 대표 센터로 폴백. "
                          "네트워크/키를 확인하세요.")
            fb["api_error"] = str(e)
            return fb

        mapped = [_map_center(it) for it in _extract_items(data)]
        total = _extract_total(data)
        if mapped:  # 성공 결과만 캐시
            cache.set(ck, (mapped, total))

    items = _filter(mapped, region, keyword)[:limit]
    return {
        "items": items,
        "count": len(items),
        "total_count": total,   # 전국 청년센터 전체 건수(필터 전)
        "is_mock": False,
        "source": "온통청년 청년센터 API getSpace (한국고용정보원, 공공데이터포털)",
        "note": ("라이브 API 응답입니다. 지역/키워드 필터는 전체 목록을 받아 클라이언트단에서 적용합니다. "
                 "정책 매칭 후 오프라인 상담·서류 지원을 위한 인근 청년센터 연결 용도입니다."),
    }

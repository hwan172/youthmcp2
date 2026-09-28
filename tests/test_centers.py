"""청년센터(getSpace) 클라이언트 테스트 — mock 폴백·필드 매핑·필터 (네트워크 불필요)."""
from __future__ import annotations

from policy_mcp.clients import youthcenter_centers as centers


async def test_no_key_falls_back_to_mock():
    r = await centers.search_centers(None, limit=8)
    assert r["is_mock"] is True
    assert r["count"] >= 1
    assert "내장" in r["note"] or "미설정" in r["note"]


async def test_mock_region_filter_seoul():
    r = await centers.search_centers(None, region="서울", limit=8)
    assert r["is_mock"] is True
    assert r["count"] >= 1
    assert all("서울" in it["sido"] or "서울" in it["address"] for it in r["items"])


async def test_mock_region_filter_excludes_others():
    r = await centers.search_centers(None, region="부산", limit=8)
    for it in r["items"]:
        assert "서울" not in it["sido"]


async def test_mock_keyword_filter():
    r = await centers.search_centers(None, keyword="마포", limit=8)
    assert r["count"] >= 1
    assert all("마포" in (it["name"] + it["address"] + it["sigungu"]) for it in r["items"])


def test_map_center_pulls_expected_fields():
    item = {
        "cntrSn": "10273",
        "cntrNm": "장성군 청년센터 아우름",
        "cntrAddr": "전라남도 장성군 장성읍 영천로",
        "cntrDaddr": "231-1",
        "cntrTelno": "061-390-7085",
        "cntrUrlAddr": "https://www.jangseong.go.kr/home/ingu-youth",
        "stdgCtpvCdNm": "전남광주특별시",
        "stdgSggCdNm": "장성군",
    }
    m = centers._map_center(item)
    assert m["center_id"] == "10273"
    assert m["name"] == "장성군 청년센터 아우름"
    assert m["tel"] == "061-390-7085"
    assert m["url"] == "https://www.jangseong.go.kr/home/ingu-youth"
    assert m["sido"] == "전남광주특별시"
    assert m["sigungu"] == "장성군"
    # 상세주소(cntrDaddr)가 주소에 합쳐짐
    assert "231-1" in m["address"] and "장성읍" in m["address"]


def test_region_match_partial():
    it = {"sido": "서울특별시", "sigungu": "마포구", "address": "서울특별시 마포구 월드컵로1길 14"}
    assert centers._region_match("서울", it) is True
    assert centers._region_match("마포", it) is True
    assert centers._region_match("부산", it) is False


def test_keyword_match_partial():
    it = {"name": "서울청년센터 마포", "address": "서울특별시 마포구", "sigungu": "마포구"}
    assert centers._keyword_match("마포", it) is True
    assert centers._keyword_match("청년센터", it) is True
    assert centers._keyword_match("없는키워드", it) is False


async def test_limit_is_bounded():
    r = await centers.search_centers(None, limit=2)
    assert r["count"] <= 2

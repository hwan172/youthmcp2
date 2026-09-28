"""온통청년 API 클라이언트 mock 폴백 테스트 (네트워크 불필요)."""
from __future__ import annotations

from policy_mcp.clients import youthcenter


async def test_no_key_falls_back_to_mock():
    r = await youthcenter.search_policies(None, query="월세 지원", page_size=5)
    assert r["is_mock"] is True
    assert r["count"] >= 1
    assert "월세" in r["note"] or "mock" in r["note"].lower() or "코퍼스" in r["note"]


async def test_mock_returns_relevant_policy():
    r = await youthcenter.search_policies(None, query="월세 지원", page_size=5)
    ids = [it["policy_id"] for it in r["items"]]
    assert "youth-monthly-rent" in ids


async def test_mock_region_filter():
    r = await youthcenter.search_policies(None, query="청년수당", region="부산", page_size=6)
    ids = [it["policy_id"] for it in r["items"]]
    assert "seoul-youth-allowance" not in ids


async def test_mock_empty_query_lists_policies():
    r = await youthcenter.search_policies(None, query="", page_size=4)
    assert r["is_mock"] is True
    assert 1 <= r["count"] <= 4


def test_extract_items_handles_wrappings():
    assert youthcenter._extract_items({"result": {"youthPolicyList": [{"a": 1}]}}) == [{"a": 1}]
    assert youthcenter._extract_items({"plcyLst": [{"b": 2}]}) == [{"b": 2}]
    assert youthcenter._extract_items([{"c": 3}]) == [{"c": 3}]
    assert youthcenter._extract_items({"weird": 1}) == []
    assert youthcenter._extract_items("nonsense") == []


def test_map_item_pulls_expected_fields():
    item = {"plcyNo": "P1", "plcyNm": "테스트정책", "sprtTrgtMinAge": "19",
            "sprtTrgtMaxAge": "34", "aplyUrlAddr": "http://x"}
    m = youthcenter._map_item(item)
    assert m["policy_id"] == "P1"
    assert m["name"] == "테스트정책"
    assert m["age_min"] == 19 and m["age_max"] == 34
    assert m["apply_url"] == "http://x"

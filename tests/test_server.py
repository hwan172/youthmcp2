"""MCP 서버 툴 규약 테스트 — 툴 5개·이름 규약·desc 길이 (네트워크 불필요)."""
from __future__ import annotations

import re

from policy_mcp.server import mcp

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


async def _tools():
    """list_tools() → {name: tool} 로 정리."""
    return {t.name: t for t in await mcp.list_tools()}


async def test_exactly_six_tools():
    tools = await _tools()
    assert len(tools) == 6


async def test_expected_tool_names_present():
    names = set((await _tools()).keys())
    assert names == {
        "search_youth_policies",
        "check_eligibility",
        "get_policy_detail",
        "remember_user_profile",
        "recall_user_profile",
        "find_youth_centers",
    }


async def test_tool_names_valid_and_no_kakao():
    for name in (await _tools()).keys():
        assert _NAME_RE.match(name), name
        assert "kakao" not in name.lower()


async def test_descriptions_within_1024_and_bilingual():
    for name, tool in (await _tools()).items():
        desc = tool.description or ""
        assert 0 < len(desc) <= 1024, f"{name}: {len(desc)}"
        assert "Youth Policy Navigator" in desc
        assert "청년 정책 내비게이터" in desc


async def test_annotations_have_five_hints():
    for name, tool in (await _tools()).items():
        ann = tool.annotations
        assert ann is not None
        assert ann.title
        assert ann.readOnlyHint is not None
        assert ann.destructiveHint is not None
        assert ann.idempotentHint is not None
        assert ann.openWorldHint is not None


async def test_mutating_tool_is_not_readonly():
    tools = await _tools()
    assert tools["remember_user_profile"].annotations.readOnlyHint is False
    assert tools["search_youth_policies"].annotations.readOnlyHint is True

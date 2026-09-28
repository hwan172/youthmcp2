"""개인화 메모리(SQLite + BM25 회상) 테스트 (네트워크 불필요)."""
from __future__ import annotations

from policy_mcp import memory


def test_save_and_recall_relevant(tmp_path):
    db = str(tmp_path / "m.db")
    memory.save("u1", "나는 서울에 산다", db_path=db)
    memory.save("u1", "연소득 2800만원이다", db_path=db)
    r = memory.recall("u1", "소득 얼마", k=2, db_path=db)
    assert r["count"] >= 1
    assert any("연소득" in x["note"] for x in r["results"])


def test_user_isolation(tmp_path):
    db = str(tmp_path / "m.db")
    memory.save("a", "서울 거주 27세", db_path=db)
    memory.save("b", "부산 거주 30세", db_path=db)
    notes = [x["note"] for x in memory.recall("a", "", db_path=db)["results"]]
    assert "서울 거주 27세" in notes
    assert "부산 거주 30세" not in notes


def test_recall_unknown_user_is_empty(tmp_path):
    db = str(tmp_path / "m.db")
    r = memory.recall("nobody", "뭐든", db_path=db)
    assert r["count"] == 0 and r["results"] == []


def test_save_requires_both_fields(tmp_path):
    db = str(tmp_path / "m.db")
    assert memory.save("", "x", db_path=db)["saved"] is False
    assert memory.save("u", "", db_path=db)["saved"] is False


def test_empty_query_returns_recent(tmp_path):
    db = str(tmp_path / "m.db")
    memory.save("u", "첫번째", db_path=db)
    memory.save("u", "두번째", db_path=db)
    r = memory.recall("u", "", k=5, db_path=db)
    assert r["count"] == 2
    assert r["results"][0]["note"] == "두번째"  # 최신 우선


def test_recall_notes_returns_text_list(tmp_path):
    db = str(tmp_path / "m.db")
    memory.save("u", "구직 중", db_path=db)
    notes = memory.recall_notes("u", "", db_path=db)
    assert notes == ["구직 중"]

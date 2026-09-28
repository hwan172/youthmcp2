"""개인화 메모리 (contextual retrieval).

사용자별 상황(나이·지역·소득·취업상태 등)과 자유텍스트 노트를 저장하고, 질의와 관련된
항목을 BM25로 회상한다. 저장소는 SQLite(stdlib) 단일 파일 — 외부 의존성 0. user_key로 사용자 격리.

주의: KC 컨테이너 파일시스템은 재배포 시 초기화되므로, 메모리는 '인스턴스 수명 내' 유지된다
(데모/세션 목적). 영구 보존이 필요하면 외부 DB로 교체한다. 경로는 MEMORY_DB_PATH로 재정의.
"""
from __future__ import annotations

import os
import sqlite3
import time

from .retrieval import Chunk, bm25_search

_DEFAULT_DB = os.environ.get("MEMORY_DB_PATH", "policy_memory.db")


def _connect(db_path: str | None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or _DEFAULT_DB, check_same_thread=False)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS memories ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_key TEXT NOT NULL, "
        "note TEXT NOT NULL, ts REAL NOT NULL)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user ON memories(user_key)")
    return conn


def save(user_key: str, note: str, *, db_path: str | None = None) -> dict:
    """사용자 상황/선호 한 줄을 저장한다."""
    user_key = (user_key or "").strip()
    note = (note or "").strip()
    if not user_key or not note:
        return {"saved": False, "error": "user_key와 note가 모두 필요합니다."}
    conn = _connect(db_path)
    try:
        with conn:
            conn.execute("INSERT INTO memories(user_key, note, ts) VALUES (?, ?, ?)",
                         (user_key, note, time.time()))
            total = conn.execute("SELECT COUNT(*) FROM memories WHERE user_key=?",
                                 (user_key,)).fetchone()[0]
    finally:
        conn.close()
    return {"saved": True, "note": note, "total_for_user": total}


def _user_chunks(conn: sqlite3.Connection, user_key: str) -> list[tuple[int, str, float, Chunk]]:
    rows = conn.execute(
        "SELECT id, note, ts FROM memories WHERE user_key=? ORDER BY ts DESC", (user_key,)
    ).fetchall()
    return [(rid, note, ts,
             Chunk(id=str(rid), title="메모리", source="user_memory", context="사용자 저장 상황/선호",
                   body=note, domain="memory"))
            for rid, note, ts in rows]


def recall(user_key: str, query: str = "", k: int = 4, *, db_path: str | None = None) -> dict:
    """질의와 관련된 사용자 메모리 top-k를 회상한다(질의 비면 최근 항목)."""
    user_key = (user_key or "").strip()
    if not user_key:
        return {"results": [], "count": 0, "note": "user_key가 필요합니다."}
    conn = _connect(db_path)
    try:
        items = _user_chunks(conn, user_key)
    finally:
        conn.close()

    if not items:
        return {"results": [], "count": 0,
                "note": "이 사용자에 대한 저장된 메모리가 없습니다."}

    if query.strip():
        chunks = [c for *_rest, c in items]
        hits = bm25_search(query, chunks, k)
        if hits:
            by_id = {c.id: (rid, note, ts) for rid, note, ts, c in items}
            results = [{"note": c.body, "ts": by_id[c.id][2], "score": s} for s, c in hits]
        else:  # 매칭 0건이면 최근 항목으로 폴백
            results = [{"note": note, "ts": ts} for _rid, note, ts, _c in items[:k]]
    else:
        results = [{"note": note, "ts": ts} for _rid, note, ts, _c in items[:k]]

    return {
        "results": results,
        "count": len(results),
        "note": ("이 사용자의 저장된 상황/선호다. 정책 추천·자격 판정에 자연스럽게 반영하라."),
    }


def recall_notes(user_key: str, query: str = "", k: int = 20, *, db_path: str | None = None) -> list[str]:
    """자격 판정용: 사용자 노트 텍스트만 리스트로 회상한다(내부 사용)."""
    r = recall(user_key, query, k, db_path=db_path)
    return [x["note"] for x in r["results"]]

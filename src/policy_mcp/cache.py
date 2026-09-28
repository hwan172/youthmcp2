"""아주 가벼운 단일 프로세스 in-memory TTL 캐시 (외부 의존 없음).

평균 응답속도 개선용. 라이브(성공) 결과만 캐시한다 — mock/실패 결과는 호출부에서 캐시하지 않는다.
"""
from __future__ import annotations

import time
from typing import Any

_store: dict[Any, tuple[float, Any]] = {}


def get(key: Any, ttl_s: float):
    hit = _store.get(key)
    if hit is not None and (time.monotonic() - hit[0]) < ttl_s:
        return hit[1]
    return None


def set(key: Any, value) -> None:
    _store[key] = (time.monotonic(), value)


def clear() -> None:
    _store.clear()

"""환경설정 로딩.

API 키는 환경변수(.env)에서만 읽는다 — 소스에 하드코딩 금지.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# 프로젝트 루트의 .env 를 로드한다(있을 경우). 없으면 조용히 넘어간다.
load_dotenv()


@dataclass(frozen=True)
class Settings:
    # 온통청년(youthcenter.go.kr) OPEN API 키 3종. 인증방식은 쿼리파라미터 apiKeyNm.
    # 미설정이면 None → 클라이언트는 내장 코퍼스 기반 mock 으로 폴백.
    #
    #   youthcenter_policy_key   : 청년정책 목록  (/go/ythip/getPlcy)    ← 정책 검색·자격판정
    #   youthcenter_contents_key : 정책소식 콘텐츠 (/go/ythip/getContent) ← 향후 툴 후보
    #   youthcenter_centers_key  : 청년센터·공간  (/go/ythip/getSpace)   ← 향후 툴 후보
    youthcenter_policy_key: str | None
    youthcenter_contents_key: str | None
    youthcenter_centers_key: str | None
    # 서버 실행 설정
    transport: str
    host: str
    port: int


def _env(name: str) -> str | None:
    # 빈 문자열도 미설정으로 취급
    return os.environ.get(name) or None


def load_settings() -> Settings:
    return Settings(
        # YOUTHCENTER_API_KEY_POLICY 우선, 없으면 구 단일키(YOUTHCENTER_API_KEY)로 폴백(하위호환).
        youthcenter_policy_key=_env("YOUTHCENTER_API_KEY_POLICY") or _env("YOUTHCENTER_API_KEY"),
        youthcenter_contents_key=_env("YOUTHCENTER_API_KEY_CONTENTS"),
        youthcenter_centers_key=_env("YOUTHCENTER_API_KEY_CENTERS"),
        transport=os.environ.get("MCP_TRANSPORT", "stdio").lower(),
        host=os.environ.get("MCP_HOST", "0.0.0.0"),
        # 클라우드가 PORT를 주입하는 경우(Git 소스 배포)도 수용
        port=int(os.environ.get("MCP_PORT") or os.environ.get("PORT") or "8000"),
    )


settings = load_settings()

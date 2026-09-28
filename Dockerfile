# 카카오 PlayMCP in KC 배포용 — Streamable HTTP MCP 서버
#
# ⚠️ KC는 linux/amd64 이미지만 활성화됩니다. Apple Silicon(arm64) Mac에서는 반드시:
#       docker build --platform linux/amd64 -t policy-mcp .
#     (arm64 이미지는 서버 활성화에 실패)
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# 의존성 설치 (소스 변경과 분리해 레이어 캐시 활용)
# uv.lock 포함 → 로컬과 동일 버전으로 재현 빌드
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --no-dev --frozen

# ⚠️ 키(YOUTHCENTER_API_KEY) 미발급 상태 → .env 베이킹 비활성화.
#    키 발급 후, 비공개(private) 레포 배포 시 아래 줄의 주석을 해제해 실제 .env 를 이미지에 포함한다.
#    (.env 를 이미지에 넣으면 절대 public 레포로 전환하지 말 것)
# COPY .env* ./

# 비루트 사용자로 실행
RUN useradd -m appuser && chown -R appuser /app
USER appuser

# 원격(Streamable HTTP) 모드로 기동 → http://<host>:8000/mcp/
ENV MCP_TRANSPORT=http \
    MCP_HOST=0.0.0.0 \
    PORT=8080
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import os,socket; socket.create_connection(('127.0.0.1',int(os.environ.get('PORT',8080))),2)" || exit 1
CMD ["uv", "run", "--no-sync", "policy-mcp"]

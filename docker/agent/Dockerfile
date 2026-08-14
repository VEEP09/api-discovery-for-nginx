# Agent 이미지 (distroless — 셸/패키지매니저 없음, docker exec 셸 진입 불가)
# 빌드 컨텍스트는 agent/ 디렉토리.
#   docker compose -f docker/agent/docker-compose.yml up -d --build

# ── builder: 의존성 설치 ──────────────────────────────────
FROM python:3.11-slim AS builder
WORKDIR /agent
COPY requirements.txt .
RUN pip install --no-cache-dir --target=/deps -r requirements.txt

# ── final: distroless (셸 없음) ───────────────────────────
FROM gcr.io/distroless/python3-debian12
WORKDIR /agent
COPY --from=builder /deps /deps
COPY agent.py .
ENV PYTHONPATH=/deps
ENV PYTHONUNBUFFERED=1

# 설정·커서·로그는 이미지에 굽지 않고 볼륨으로 마운트한다 (compose 참고).
ENTRYPOINT ["python3", "agent.py", "--config", "agent_config.yaml"]

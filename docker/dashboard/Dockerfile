# Dashboard 이미지 (distroless — 셸/패키지매니저 없음, docker exec 셸 진입 불가)
# 빌드 컨텍스트는 저장소 루트.
#   docker compose -f docker/dashboard/docker-compose.yml up -d --build

# ── builder: 의존성 설치 ──────────────────────────────────
FROM python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt .
# torch는 CPU 전용 휠로 받는다. 기본 PyPI 인덱스는 CUDA 빌드를 당겨오는데
# (nvidia-* + triton 만 2.5GB+) 이 프로젝트는 CPU 추론만 한다.
# PEP 440 상 로컬 버전 `X.Y.Z+cpu` 가 `X.Y.Z` 보다 높게 정렬되므로 CPU 휠이 선택된다.
# 아래 검증 단계는 그래도 CUDA 빌드가 섞여 들어왔을 때, 조용히 5GB 이미지가
# 만들어지는 대신 빌드를 그 자리에서 실패시킨다.
RUN pip install --no-cache-dir --target=/deps \
      --extra-index-url https://download.pytorch.org/whl/cpu \
      -r requirements.txt \
 && python -c "import sys; sys.path.insert(0, '/deps'); import torch; \
      assert torch.__version__.endswith('+cpu'), 'CUDA build leaked in: ' + torch.__version__; \
      print('torch OK:', torch.__version__)"

# ── syslibs: distroless와 동일한 debian 12(bookworm)에서 시스템 라이브러리 확보 ──
# (torch가 필요로 하는 libstdc++/libgcc. glibc 버전을 distroless와 맞춰야 함)
FROM debian:12-slim AS syslibs
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# ── final: distroless (셸 없음) ───────────────────────────
FROM gcr.io/distroless/python3-debian12
WORKDIR /app
COPY --from=syslibs /usr/lib/x86_64-linux-gnu/libstdc++.so.6 /usr/lib/x86_64-linux-gnu/
COPY --from=syslibs /usr/lib/x86_64-linux-gnu/libgcc_s.so.1 /usr/lib/x86_64-linux-gnu/
COPY --from=builder /deps /deps
COPY . .
ENV PYTHONPATH=/deps
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
ENTRYPOINT ["python3", "serve.py"]

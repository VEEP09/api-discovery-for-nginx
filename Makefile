.PHONY: install setup start stop restart run logs \
        docker-start docker-stop docker-restart docker-build docker-logs

PORT    ?= 8080
CONFIG  ?= config/settings.yaml
PID_FILE = .pid

# ── 최초 설치 ─────────────────────────────────────────────────────────────────
install:
	@echo "── 의존성 설치 ──────────────────────────────"
	pip3 install -r requirements.txt
	@echo ""
	@echo "── 디렉토리 생성 ────────────────────────────"
	mkdir -p output logs
	@echo ""
	@echo "── 설치 완료 ────────────────────────────────"
	@echo "  다음 단계: make setup  (인증 토큰 설정)"
	@echo "             make start  (서버 시작)"

# ── 인증 토큰 설정 (에이전트 연동용) ─────────────────────────────────────────
setup:
	@echo "── Dashboard 설정 ───────────────────────────"
	@echo ""
	@echo "에이전트 인증 토큰을 설정합니다."
	@echo "에이전트의 agent_config.yaml 의 ingest_token 과 동일한 값이어야 합니다."
	@echo "(비워두면 인증 없이 동작 — 로컬/단일 VM 모드)"
	@echo ""
	@read -rp "인증 토큰: " TOKEN; \
	python3 -c " \
import yaml, sys; \
cfg = yaml.safe_load(open('$(CONFIG)')); \
cfg.setdefault('ingest', {})['token'] = '$$TOKEN'; \
yaml.dump(cfg, open('$(CONFIG)', 'w'), default_flow_style=False, allow_unicode=True); \
print('설정 완료: $(CONFIG)') \
	"

# ── 서버 실행 ─────────────────────────────────────────────────────────────────
start:
	@mkdir -p logs
	nohup python3 serve.py --port $(PORT) > logs/serve.log 2>&1 & echo $$! > $(PID_FILE)
	@echo "서버 시작 (PID: $$(cat $(PID_FILE)), port: $(PORT))"
	@echo "로그: logs/serve.log"

stop:
	@if [ -f $(PID_FILE) ]; then \
		PID=$$(cat $(PID_FILE)); \
		if kill -0 $$PID 2>/dev/null; then \
			kill $$PID && echo "서버 종료 (PID: $$PID)"; \
		else \
			echo "이미 종료됨"; \
		fi; \
		rm -f $(PID_FILE); \
	else \
		pkill -f "serve.py" 2>/dev/null && echo "서버 종료" || echo "실행 중인 서버 없음"; \
	fi

restart: stop
	@sleep 1
	@$(MAKE) start

run:
	python3 serve.py --port $(PORT)

logs:
	@if [ -f logs/serve.log ]; then \
		tail -f logs/serve.log; \
	else \
		echo "로그 파일 없음 (logs/serve.log)"; \
	fi

status:
	@if [ -f $(PID_FILE) ] && kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
		echo "실행 중 (PID: $$(cat $(PID_FILE)), port: $(PORT))"; \
	else \
		echo "실행 중이지 않음"; \
	fi

# ── Docker (Dashboard) ───────────────────────────────────────────────────────
# Docker 설정은 docker/ 아래로 분리됨. 에이전트는 docker/agent/ 참고.
DASH_COMPOSE = docker/dashboard/docker-compose.yml

docker-build:
	docker compose -f $(DASH_COMPOSE) up -d --build

docker-start:
	docker compose -f $(DASH_COMPOSE) up -d

docker-stop:
	docker compose -f $(DASH_COMPOSE) down

docker-restart:
	docker compose -f $(DASH_COMPOSE) restart

docker-logs:
	docker compose -f $(DASH_COMPOSE) logs -f

# ── 도움말 ───────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "Dashboard VM"
	@echo "  make install    의존성 설치 + 디렉토리 생성"
	@echo "  make setup      인증 토큰 설정 (에이전트 연동 시)"
	@echo "  make start      서버 시작 (백그라운드)"
	@echo "  make stop       서버 종료"
	@echo "  make restart    서버 재시작"
	@echo "  make logs       실시간 로그"
	@echo "  make status     실행 상태 확인"
	@echo ""
	@echo "  make docker-build   Docker 이미지 빌드 + 시작"
	@echo "  make docker-start   Docker 컨테이너 시작"
	@echo "  make docker-stop    Docker 컨테이너 종료"
	@echo "  make docker-logs    Docker 로그"
	@echo ""
	@echo "Agent (NGINX VM) — agent/ 디렉토리"
	@echo "  bash agent/install.sh          에이전트 설치 (최초 1회, systemd 자동 등록)"
	@echo "  systemctl start nginx-apigent  에이전트 시작"
	@echo "  systemctl stop  nginx-apigent  에이전트 정지"
	@echo "  journalctl -u nginx-apigent -f 에이전트 로그"
	@echo "  make -C agent once             1회 실행 (cron용)"
	@echo ""

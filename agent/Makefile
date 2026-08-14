.PHONY: install start stop restart status logs once clean

SCRIPT_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
VENV       := $(SCRIPT_DIR).venv/bin/python
CONFIG     := $(SCRIPT_DIR)agent_config.yaml
PID_FILE   := $(SCRIPT_DIR).pid
LOG_FILE   := $(SCRIPT_DIR)agent.log
SERVICE    := nginx-apigent

# ── 설치 ──────────────────────────────────────────────────────────────────────
install:
	@bash $(SCRIPT_DIR)install.sh

# ── 실행 관리 ─────────────────────────────────────────────────────────────────
start:
	@if [ -f "$(PID_FILE)" ] && kill -0 $$(cat "$(PID_FILE)") 2>/dev/null; then \
		echo "이미 실행 중 (PID: $$(cat $(PID_FILE)))"; \
	else \
		nohup $(VENV) $(SCRIPT_DIR)agent.py --config $(CONFIG) \
			>> $(LOG_FILE) 2>&1 & echo $$! > $(PID_FILE); \
		echo "에이전트 시작 (PID: $$(cat $(PID_FILE)))"; \
		echo "로그: $(LOG_FILE)"; \
	fi

stop:
	@if [ -f "$(PID_FILE)" ]; then \
		PID=$$(cat "$(PID_FILE)"); \
		if kill -0 $$PID 2>/dev/null; then \
			kill $$PID && echo "에이전트 종료 (PID: $$PID)"; \
		else \
			echo "이미 종료됨"; \
		fi; \
		rm -f "$(PID_FILE)"; \
	else \
		pkill -f "agent.py" 2>/dev/null && echo "에이전트 종료" || echo "실행 중인 에이전트 없음"; \
	fi

restart: stop
	@sleep 1
	@$(MAKE) -f $(SCRIPT_DIR)Makefile start

# ── 상태 / 로그 ───────────────────────────────────────────────────────────────
status:
	@if systemctl is-active --quiet $(SERVICE) 2>/dev/null; then \
		systemctl status $(SERVICE) --no-pager -l; \
	elif [ -f "$(PID_FILE)" ] && kill -0 $$(cat "$(PID_FILE)") 2>/dev/null; then \
		echo "실행 중 (PID: $$(cat $(PID_FILE)))"; \
	else \
		echo "실행 중이지 않음"; \
	fi

logs:
	@if systemctl is-active --quiet $(SERVICE) 2>/dev/null; then \
		journalctl -u $(SERVICE) -f --no-hostname; \
	elif [ -f "$(LOG_FILE)" ]; then \
		tail -f $(LOG_FILE); \
	else \
		echo "로그 파일 없음: $(LOG_FILE)"; \
	fi

# ── 1회 실행 (cron 용) ────────────────────────────────────────────────────────
once:
	$(VENV) $(SCRIPT_DIR)agent.py --config $(CONFIG) --once

# ── 정리 ──────────────────────────────────────────────────────────────────────
clean:
	@$(MAKE) -f $(SCRIPT_DIR)Makefile stop 2>/dev/null || true
	rm -f $(PID_FILE) $(LOG_FILE)
	@echo "정리 완료"

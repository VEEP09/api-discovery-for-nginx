#!/usr/bin/env bash
# NGINX API Discovery — Agent 설치 스크립트
# 사용법: bash install.sh
set -euo pipefail

# ── 색상 ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${GREEN}[✔]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✘] $*${NC}"; exit 1; }
step()  { echo -e "\n${CYAN}${BOLD}▶ $*${NC}"; }
ask()   { echo -e "${BOLD}$*${NC}"; }

# root가 아니면 sudo를 투명하게 사용
_sudo() {
    if [[ $EUID -eq 0 ]]; then "$@"; else sudo "$@"; fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
CONFIG="$SCRIPT_DIR/agent_config.yaml"
SERVICE_NAME="nginx-apigent"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo -e "${CYAN}${BOLD}"
echo "╔═══════════════════════════════════════════╗"
echo "║   NGINX API Discovery — Agent Installer   ║"
echo "╚═══════════════════════════════════════════╝${NC}"
echo ""

# ── 1. Python 확인 ───────────────────────────────────────────────────────────
step "Python 확인"

PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3.9 python3.8 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VER=$($cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [[ $MAJOR -ge 3 && $MINOR -ge 8 ]]; then
            PYTHON="$cmd"
            info "Python $VER ($cmd)"
            break
        fi
    fi
done
[[ -z "$PYTHON" ]] && error "Python 3.8 이상이 필요합니다."

# ── 2. 가상 환경 + 의존성 ────────────────────────────────────────────────────
step "가상 환경 설정"

if [[ ! -d "$VENV_DIR" || ! -f "$VENV_DIR/bin/pip" ]]; then
    [[ -d "$VENV_DIR" ]] && { warn "가상 환경 불완전 — 재생성합니다."; rm -rf "$VENV_DIR"; }
    info "가상 환경 생성: $VENV_DIR"

    # venv 생성 시도 — 실패 시 python3-venv 패키지 자동 설치
    if ! "$PYTHON" -m venv "$VENV_DIR" 2>/dev/null; then
        warn "venv 생성 실패 — python3-venv 패키지 설치 시도 중..."
        rm -rf "$VENV_DIR"
        PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        if command -v apt-get &>/dev/null; then
            _sudo apt-get install -y -qq "python${PY_VER}-venv" || _sudo apt-get install -y -qq python3-venv
        elif command -v yum &>/dev/null; then
            _sudo yum install -y -q python3-venv
        else
            error "python3-venv 패키지를 수동으로 설치한 후 다시 실행하세요."
        fi
        "$PYTHON" -m venv "$VENV_DIR" || error "가상 환경 생성 실패"
    fi
    info "가상 환경 생성 완료"
else
    info "기존 가상 환경 재사용: $VENV_DIR"
fi

info "pyyaml 설치 중..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet pyyaml
info "설치 완료"

# ── 3. 설정 파일 ─────────────────────────────────────────────────────────────
step "에이전트 설정"

# YAML 단일 필드 읽기
read_yaml_field() {
    local key="$1" default="$2"
    if [[ -f "$CONFIG" ]]; then
        val=$(grep "^${key}:" "$CONFIG" | head -1 \
              | sed 's/^[^:]*: *//' | tr -d '"' | tr -d "'" | xargs 2>/dev/null || echo "")
        echo "${val:-$default}"
    else
        echo "$default"
    fi
}

CUR_URL=$(read_yaml_field "dashboard_url" "http://192.168.1.100:8080")
CUR_TOKEN=$(read_yaml_field "ingest_token" "")
CUR_LOG=$(read_yaml_field "log_path" "/var/log/nginx/api_access.log")
CUR_ROTATE_DIR=$(read_yaml_field "log_rotate_dir" "/var/log/nginx/old")
CUR_INTERVAL=$(read_yaml_field "poll_interval" "30")

echo ""
ask "Dashboard VM 주소 (예: http://192.168.1.100:8080)"
read -rp "  → [${CUR_URL}]: " INPUT_URL
DASHBOARD_URL="${INPUT_URL:-$CUR_URL}"

echo ""
ask "인증 토큰 (Dashboard VM config/settings.yaml 의 ingest.token 값)"
if [[ -n "$CUR_TOKEN" && "$CUR_TOKEN" != "change-me-to-a-strong-secret" ]]; then
    read -rp "  → [현재 값 유지, Enter]: " INPUT_TOKEN
    INGEST_TOKEN="${INPUT_TOKEN:-$CUR_TOKEN}"
else
    read -rp "  → : " INPUT_TOKEN
    [[ -z "$INPUT_TOKEN" ]] && error "인증 토큰은 필수입니다."
    INGEST_TOKEN="$INPUT_TOKEN"
fi

echo ""
ask "NGINX 로그 파일 경로"
read -rp "  → [${CUR_LOG}]: " INPUT_LOG
LOG_PATH="${INPUT_LOG:-$CUR_LOG}"

echo ""
ask "logrotate 보관 디렉토리 (없으면 Enter 건너뜀)"
read -rp "  → [${CUR_ROTATE_DIR}]: " INPUT_ROTATE
ROTATE_DIR="${INPUT_ROTATE:-$CUR_ROTATE_DIR}"

echo ""
ask "폴링 주기 (초, 기본 30)"
read -rp "  → [${CUR_INTERVAL}]: " INPUT_INTERVAL
POLL_INTERVAL="${INPUT_INTERVAL:-$CUR_INTERVAL}"

# ── 설정 파일 생성 / 업데이트 ────────────────────────────────────────────────
update_field() {
    local key="$1" val="$2"
    if grep -q "^${key}:" "$CONFIG" 2>/dev/null; then
        sed -i "s|^${key}:.*|${key}: \"${val}\"|" "$CONFIG"
    else
        echo "${key}: \"${val}\"" >> "$CONFIG"
    fi
}

# 최초 설치면 템플릿으로 초기화
if [[ ! -f "$CONFIG" ]]; then
    cat > "$CONFIG" <<CFGEOF
dashboard_url: ""
ingest_token: ""
log_path: "/var/log/nginx/api_access.log"
log_rotate_dir: "/var/log/nginx/old"
log_rotate_pattern: "api_access.log-*.gz"
cursor_file: "${SCRIPT_DIR}/agent_cursor.json"
batch_size: 5000
poll_interval: 30
retain_days: 7
skip_error_responses: true
exclude_prefixes:
  - "/static"
  - "/assets"
  - "/favicon.ico"
  - "/robots.txt"
  - "/health"
  - "/ping"
exclude_extensions:
  - ".png"
  - ".jpg"
  - ".gif"
  - ".svg"
  - ".ico"
  - ".webp"
  - ".woff2"
CFGEOF
fi

update_field "dashboard_url"  "$DASHBOARD_URL"
update_field "ingest_token"   "$INGEST_TOKEN"
update_field "log_path"       "$LOG_PATH"
update_field "log_rotate_dir" "$ROTATE_DIR"
update_field "poll_interval"  "$POLL_INTERVAL"

info "설정 저장: $CONFIG"

# ── 4. 연결 테스트 ───────────────────────────────────────────────────────────
step "Dashboard 연결 테스트"

if command -v curl &>/dev/null; then
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
                --max-time 5 "${DASHBOARD_URL}/api/summary" 2>/dev/null || echo "000")
    if [[ "$HTTP_CODE" == "200" ]]; then
        info "Dashboard 연결 성공 (HTTP $HTTP_CODE)"
    else
        warn "Dashboard 연결 실패 (HTTP $HTTP_CODE) — 나중에 확인하세요."
    fi
else
    warn "curl 없음 — 연결 테스트 건너뜀"
fi

# ── 5. systemd 서비스 등록 ───────────────────────────────────────────────────
step "systemd 서비스 등록 (${SERVICE_NAME})"

if ! command -v systemctl &>/dev/null; then
    warn "systemd를 찾을 수 없습니다."
    warn "수동 실행: $VENV_DIR/bin/python $SCRIPT_DIR/agent.py"
else
    # root가 아니면 sudo 사용 — 패스워드 프롬프트가 뜰 수 있음
    if [[ $EUID -ne 0 ]]; then
        info "systemd 등록에 sudo 권한이 필요합니다."
    fi

    _sudo tee "$SERVICE_FILE" > /dev/null <<SVCEOF
[Unit]
Description=NGINX API Discovery Agent
After=network.target

[Service]
Type=simple
ExecStart=${VENV_DIR}/bin/python ${SCRIPT_DIR}/agent.py --config ${CONFIG}
WorkingDirectory=${SCRIPT_DIR}
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
SVCEOF

    _sudo systemctl daemon-reload
    _sudo systemctl enable  "$SERVICE_NAME"
    _sudo systemctl restart "$SERVICE_NAME"

    # 잠깐 기다려서 실제 기동 여부 확인
    sleep 2
    if _sudo systemctl is-active --quiet "$SERVICE_NAME"; then
        info "서비스 실행 중: $SERVICE_NAME"
    else
        warn "서비스 시작 실패 — 로그 확인: journalctl -u $SERVICE_NAME -n 30"
    fi
fi

# ── 완료 ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}══════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  설치 완료!${NC}"
echo -e "${GREEN}${BOLD}══════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BOLD}서비스 시작${NC}      systemctl start  ${SERVICE_NAME}"
echo -e "  ${BOLD}서비스 정지${NC}      systemctl stop   ${SERVICE_NAME}"
echo -e "  ${BOLD}서비스 재시작${NC}    systemctl restart ${SERVICE_NAME}"
echo -e "  ${BOLD}서비스 상태${NC}      systemctl status  ${SERVICE_NAME}"
echo -e "  ${BOLD}실시간 로그${NC}      journalctl -u ${SERVICE_NAME} -f"
echo ""
echo -e "  ${BOLD}설정 파일${NC}        ${CONFIG}"
echo ""

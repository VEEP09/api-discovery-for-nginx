# NGINX API Discovery

NGINX 액세스 로그를 실시간으로 분석해 API Inventory를 자동 구성하고, 머신러닝 기반 이상 탐지 결과를 웹 대시보드로 제공하는 서비스입니다.

## 주요 기능

- **API Inventory 자동 구성** — NGINX 로그에서 (method, normalized URI) 조합을 추출해 endpoint 목록 생성
- **Shadow API 탐지** — OpenAPI 스펙과 실제 트래픽 비교로 문서화되지 않은 API 검출
- **ML 이상 탐지** — AutoEncoder + LSTM 기반 비정상 요청 패턴 탐지
- **Off-hour 탐지** — 업무 시간 외 비정상 트래픽 감지
- **Suspicious IP 탐지** — 비정상 시퀀스 패턴을 보이는 IP 식별
- **Try Request** — 대시보드에서 실제 API 요청 직접 실행
- **Connected Agents 관제** — 연동된 NGINX 서버(에이전트)의 Online/Offline/Unknown 상태 및 NGINX 프로세스 상태 모니터링
- **NGINX Plus 메트릭** — REST API 기반 연결 수·HTTP 요청·SSL·프로세스·라이선스(만료 D-day) 표시
- **다크/라이트 테마** — 상단바 토글 버튼으로 전환, 선택은 브라우저에 저장(기본 다크)

---

## 배포 방식

본 시스템은 **에이전트(Agent) 전용 아키텍처**로 동작합니다. NGINX 로그 수집은 항상 에이전트가 담당하며, 대시보드는 수신·분석·시각화만 수행합니다.

### 에이전트 모드 (기본 구조)

NGINX 서버(에이전트)와 대시보드를 HTTP로 연동합니다.

```
┌─────────────────────────────┐         ┌───────────────────────────────┐
│        NGINX Plus VM        │         │         Dashboard VM          │
│                             │         │                               │
│  /var/log/nginx/            │         │  config/settings.yaml         │
│  └── api_access.log         │         │  output/api_logs.db (SQLite)  │
│           ↓                 │  HTTP   │                               │
│  agent/agent.py             │  POST   │  POST /api/ingest  ← 수신     │
│  - 로그 증분 파싱           │ ──────► │  - URI 정규화 → DB 저장       │
│  - 필터링 / Bearer 인증     │         │                               │
│  - 배치 전송 (30초마다)     │         │  GET  / → 대시보드 UI         │
│  - NGINX 상태 / Plus 메트릭 │         │  GET  /api/summary            │
│                             │         │  GET  /api/agents             │
│  agent_cursor.json          │         │  POST /api/pipeline/run       │
│  (읽기 위치 추적)           │         │                               │
└─────────────────────────────┘         └───────────────────────────────┘
```

- **2-VM 구성 (권장)**: NGINX 서버와 대시보드를 분리. 다수의 NGINX 서버를 단일 대시보드에 연동 가능.
- **단일 VM 구성**: 한 VM에 에이전트와 대시보드를 함께 설치하고, 에이전트의 `dashboard_url`을 `http://localhost:8080` 으로 설정.

---

## 아키텍처 — 파이프라인

```
[로그 수집 — 에이전트]
├── 당일 로그: inode + offset cursor로 증분 읽기 (logrotate 자동 감지)
└── Rotated 로그: 파일 단위 cursor (-1 = 완전 처리 sentinel)
        ↓ HTTP POST /api/ingest (Bearer 인증)
[SQLite DB — 7일 보관, 초과분 자동 purge]
        ↓
[Pipeline 실행 시]
├── 0단계: 보관 기간 초과 로그 정리 (purge)
├── 1단계: SQL 집계 → API Inventory 구축 (4xx/5xx 제외)   ◀ Run Now는 여기까지
├── 2단계: Feature Engineering (최근 train_sample_size건 표본, 벡터화 + 시퀀스)
└── 3단계: AutoEncoder + LSTM 학습 + 이상 탐지
        ↓
output/ (JSON/CSV 스냅샷, 최신 3개 유지)
```

> **에러 요청 처리**: 4xx/5xx 응답은 Requests 탭(원본 로그 조회)에는 표시되지만, Inventory 및 ML 학습에서는 제외되어 정상 트래픽 기준으로 분석됩니다.

### 파이프라인 트리거

| 트리거 | 조건 | 실행 범위 |
|--------|------|-----------|
| **Manual** (Run Now) | 대시보드 Run Now 버튼 | **데이터(Inventory)만 갱신** (0~1단계, 수 초). 딥러닝 재학습은 제외 |
| **Daily** | 매일 KST 06:00 자동 실행 | **전체 파이프라인** (0~3단계, Feature + 딥러닝 재학습 포함) |

> **왜 분리했나**: 로그가 수백만 건까지 쌓이면 전체 재학습은 수십 분이 걸립니다. Run Now가 즉시 반응하도록 무거운 딥러닝 재학습은 Daily 스케줄에만 두고, 수동 실행은 Inventory/대시보드 데이터만 빠르게 갱신합니다. 이상 탐지(ML) 탭 결과는 매일 06:00에 갱신됩니다.
>
> **성능**: Inventory 집계는 SQL로 처리하고, 대시보드 읽기 경로(inventory 샘플·총계·OpenAPI 파싱)는 캐시하여 대용량 DB에서도 응답을 빠르게 유지합니다.

---

## 설치 가이드

### 사전 준비 — 인증 토큰 생성

에이전트 모드에서는 두 VM이 같은 토큰을 공유합니다.

```bash
openssl rand -hex 24
# 예: a3f9c2d18e7b4501f6c83a29d74e112b8f0e6c4d21b93a7f
```

---

### Dashboard VM

#### 옵션 1 — 직접 실행

```bash
git clone <repo> /opt/nginx-api-discovery
cd /opt/nginx-api-discovery

make install      # pip 의존성 설치 + output/ logs/ 디렉토리 생성
make setup        # 인증 토큰 설정 (프롬프트 입력)
make start        # 백그라운드 서버 시작 (포트 8080)
```

#### 옵션 2 — Docker

Docker 전용 설정은 `docker/` 디렉토리에 모여 있습니다 (기존 직접 실행 방식과 분리).

```bash
git clone <repo> /opt/nginx-api-discovery
cd /opt/nginx-api-discovery

# config/settings.yaml 의 ingest.token 먼저 직접 편집
vi config/settings.yaml

make docker-build   # = docker compose -f docker/dashboard/docker-compose.yml up -d --build
```

> 에이전트도 Docker로 실행할 수 있습니다 → [`docker/README.md`](../docker/README.md) 참고.

#### 방화벽

```bash
sudo ufw allow 8080/tcp
```

#### 정상 기동 확인

```bash
curl http://localhost:8080/api/summary
# → {"total_requests": 0, ...} 응답이 오면 OK
```

---

### Agent VM (NGINX Plus 서버)

`agent/` 폴더만 있으면 됩니다. Python과 pyyaml 외 별도 의존성 없습니다.

```bash
# agent/ 폴더를 NGINX VM에 복사
scp -r /opt/nginx-api-discovery/agent/ nginx-vm:/opt/nginx-apigent/

# NGINX VM에서 실행
cd /opt/nginx-apigent
bash install.sh
```

설치 스크립트가 순서대로 안내합니다.

```
▶ Python 확인
[✔] Python 3.11

▶ 가상 환경 설정
[✔] 설치 완료

▶ 에이전트 설정

Dashboard VM 주소
  → [http://192.168.1.100:8080]: http://10.0.0.5:8080    ← Dashboard VM IP

인증 토큰
  → : a3f9c2d18e7b4501f6c83a29d74e112b8f0e6c4d21b93a7f   ← 동일한 토큰

NGINX 로그 파일 경로
  → [/var/log/nginx/api_access.log]:                     ← Enter

logrotate 보관 디렉토리
  → [/var/log/nginx/old]:                                ← Enter

폴링 주기 (초, 기본 30)
  → [30]:                                                ← Enter

▶ Dashboard 연결 테스트
[✔] Dashboard 연결 성공 (HTTP 200)

▶ systemd 서비스 등록 (nginx-apigent)
[✔] 서비스 실행 중: nginx-apigent

══════════════════════════════════════════
  설치 완료!
══════════════════════════════════════════
```

---

## 서비스 관리

### Dashboard VM

```bash
make start        # 서버 시작
make stop         # 서버 종료
make restart      # 서버 재시작
make status       # 실행 상태 확인
make logs         # 실시간 로그

# Docker 사용 시
make docker-start
make docker-stop
make docker-logs
```

### Agent VM

```bash
systemctl start   nginx-apigent    # 시작
systemctl stop    nginx-apigent    # 정지
systemctl restart nginx-apigent    # 재시작
systemctl status  nginx-apigent    # 상태 확인
journalctl -u nginx-apigent -f     # 실시간 로그
```

---

## 설정 파일

### Dashboard VM — `config/settings.yaml`

```yaml
pipeline:
  output_dir: "./output"            # 분석 결과 저장 경로
  db_path: "./output/api_logs.db"   # 에이전트가 /api/ingest 로 적재하는 SQLite DB
  retain_days: 7                    # 로그 보관 기간 (일)
  train_sample_size: 200000         # 딥러닝 학습에 사용할 최근 로그 상한 (0 = 전체)
                                    # Inventory 집계는 항상 전체 로그 기준, 이 값은 학습 표본에만 적용

ingest:
  token: ""   # 에이전트 인증 토큰 — 에이전트의 ingest_token과 일치해야 함
              # (비워두면 인증 비활성화)

inventory:
  min_call_count: 10    # 최소 호출 횟수 (노이즈 필터링)
  output_format: "both" # csv / json / both
```

> 로그 수집은 에이전트가 전담하므로 대시보드 설정에는 로그 파일 경로가 없습니다.

### Agent VM — `agent/agent_config.yaml`

```yaml
dashboard_url: "http://192.168.1.100:8080"          # Dashboard VM 주소 (단일 VM이면 http://localhost:8080)
ingest_token: "a3f9c2d18e7b4501f6c83a29d74e112b8f0e6c4d21b93a7f"  # 인증 토큰

log_path: "/var/log/nginx/api_access.log"
log_rotate_dir: "/var/log/nginx/old"
log_rotate_pattern: "api_access.log-*.gz"

cursor_file: "./agent_cursor.json"  # 읽기 위치 저장 (재시작 시 중복 방지)
batch_size: 5000
poll_interval: 30      # 전송 주기 (초)
retain_days: 7
skip_error_responses: false   # false = 4xx/5xx도 전송 (Requests 탭 표시용)

# NGINX Plus REST API (비워두면 메트릭 수집 안 함)
nginx_plus_api: "http://127.0.0.1:411/api/9"
```

---

## NGINX 로그 포맷 설정

다음 JSON 포맷으로 NGINX 로그를 설정해야 합니다.

```nginx
log_format api_json escape=json
  '{"time":"$time_iso8601",'
  '"remote_addr":"$remote_addr",'
  '"method":"$request_method",'
  '"uri":"$uri",'
  '"query_string":"$query_string",'
  '"status":$status,'
  '"body_bytes_sent":$body_bytes_sent,'
  '"request_length":$request_length,'
  '"request_time":$request_time,'
  '"http_user_agent":"$http_user_agent",'
  '"http_authorization":"$http_authorization",'
  '"upstream_response_time":"$upstream_response_time",'
  '"host":"$host",'
  '"request_id":"$request_id"}';

access_log /var/log/nginx/api_access.log api_json;
```

> **`$host` 사용**: 도메인(domain)은 클라이언트가 보낸 Host 헤더(`$host`)에서 수집합니다. `server_name`은 nginx 설정에 따라 비어 있거나 `_`(catch-all)일 수 있어 실제 도메인을 담지 못하는 경우가 많습니다. 도메인 없이 IP로 직접 접근한 요청은 `$host`에 IP가 기록됩니다.

---

## API 엔드포인트

| 경로 | 메서드 | 설명 |
|------|--------|------|
| `/` | GET | 대시보드 UI |
| `/api/summary` | GET | 전체 요약 통계 |
| `/api/inventory` | GET | Endpoint 목록 (필터/정렬) |
| `/api/logs` | GET | 원본 로그 조회 (페이지네이션, 날짜 필터) |
| `/api/ingest` | POST | 에이전트 로그 수신 (Bearer 토큰 인증) |
| `/api/agents` | GET | 연동된 에이전트 상태/메트릭 목록 |
| `/api/anomalies/shadow` | GET | Shadow API 목록 |
| `/api/anomalies/ml-endpoints` | GET | ML 이상 탐지 결과 |
| `/api/anomalies/suspicious-ips` | GET | 의심 IP 목록 |
| `/api/anomalies/time-anomaly` | GET | Off-hour 탐지 결과 |
| `/api/anomalies/no-auth` | GET | 인증 없는 endpoint |
| `/api/anomalies/high-error` | GET | 높은 오류율 endpoint |
| `/api/pipeline/run` | POST | 파이프라인 수동 실행 |
| `/api/pipeline/status` | GET | 파이프라인 실행 상태 |
| `/api/openapi/upload` | POST | OpenAPI 스펙 업로드 |
| `/api/openapi/export-all` | GET | 전체 inventory → OpenAPI 3.0 다운로드 |
| `/api/test/request` | POST | inventory endpoint 직접 요청 실행 |

---

## 디렉토리 구조

```
nginx-api-discovery/
├── agent/                      # NGINX VM 배포용 경량 에이전트
│   ├── agent.py                # 메인 에이전트 (pyyaml만 의존)
│   ├── agent_config.yaml       # 에이전트 설정
│   ├── install.sh              # 원클릭 설치 스크립트 (systemd 방식)
│   ├── Makefile                # 에이전트 관리 명령
│   └── requirements.txt
├── docker/                     # Docker 전용 설정 (기존 방식과 분리)
│   ├── README.md               # Docker 배포 안내
│   ├── dashboard/              # 대시보드 이미지 (Dockerfile, compose)
│   ├── agent/                  # 에이전트 이미지 (Dockerfile, compose)
│   └── DOCKERHUB.*.md          # Docker Hub overview (영문/한국어 병기)
├── config/
│   └── settings.yaml           # 대시보드 전체 설정
├── src/
│   ├── collector/              # 로그 파일 읽기
│   ├── parser/                 # NGINX JSON 로그 파싱
│   ├── discovery/              # URI 정규화, Inventory, Shadow 탐지
│   ├── features/               # Feature Engineering
│   ├── models/                 # AutoEncoder, LSTM
│   ├── db/                     # SQLite 로그 저장소
│   ├── dashboard/              # FastAPI 서버 + UI
│   └── pipeline.py             # 전체 파이프라인 오케스트레이터
├── releases/                   # 릴리스 노트 (버전별)
├── output/                     # 분석 결과, SQLite DB, 학습 모델
├── serve.py                    # 대시보드 서버 진입점
├── main.py                     # 파이프라인 단독 실행 진입점
├── requirements.txt            # 런타임 의존성
├── requirements-dev.txt        # 개발·테스트 의존성 (pytest)
└── Makefile
```

---

## 요구사항

| 대상 | 요구사항 |
|------|----------|
| **Dashboard VM** | Python 3.11+, 4GB+ RAM (PyTorch 학습 시). Docker 사용 시 이미지 ~1GB |
| **Agent VM** | Python 3.8+, pyyaml |
| **공통** | NGINX JSON 포맷 액세스 로그 |

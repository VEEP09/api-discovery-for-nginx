# API Discovery for NGINX — Agent

> 🇰🇷 **한국어 문서는 이 페이지 아래쪽에 있습니다.** · Korean documentation follows below.

The log collector for **API Discovery for NGINX**. It runs on your NGINX host, tails the access log (and optionally the NGINX Plus REST API), and ships records to the dashboard.

> 🔗 **Dashboard image**: [`gusgh13900/api-discovery-nginx`](https://hub.docker.com/r/gusgh13900/api-discovery-nginx) — collector server + web UI (`:8080`). Keep it on the **same version tag** as this image.

| Image | Role | Download | On disk | Runs on |
|-------|------|----------|---------|---------|
| **`api-discovery-agent`** (this image) | NGINX log collector | ~21 MB | ~56 MB | NGINX host |
| `api-discovery-nginx` | Collector server + web dashboard (`:8080`) | ~288 MB | ~1 GB | Dashboard host |

- **Source**: open source under **Apache-2.0** — [github.com/VEEP09/api-discovery-for-nginx](https://github.com/VEEP09/api-discovery-for-nginx)
- **Architecture**: `linux/amd64` (no ARM build)
- **Configuration**: entirely through **environment variables**. Secrets are never baked into the image.
- **Footprint**: distroless, no shell, single Python dependency. It reads your logs read-only and sends them onward — nothing else.

---

## Quick start

Start the [dashboard](https://hub.docker.com/r/gusgh13900/api-discovery-nginx) first, then run this on your NGINX host:

```bash
docker run -d --name api-discovery-agent \
  --network host \
  -e DASHBOARD_URL=http://<dashboard-host>:8080 \
  -e INGEST_TOKEN=<same token as the dashboard> \
  -e LOG_PATH=/var/log/nginx/api_access.log \
  -e CURSOR_FILE=/agent/state/agent_cursor.json \
  -e NGINX_PLUS_API=http://127.0.0.1:411/api/9 \
  -v /var/log/nginx:/var/log/nginx:ro \
  -v $PWD/state:/agent/state \
  gusgh13900/api-discovery-agent:1.2.1
```

> **`INGEST_TOKEN` must be identical on both sides.** A mismatch is the usual reason an agent starts cleanly, reports `HTTP 401` in its log, and never appears in the dashboard. Leaving it empty disables authentication entirely — local use only.

Drop `--network host` if the dashboard is remote and you are not collecting NGINX Plus metrics.

---

## Environment variables

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `DASHBOARD_URL` | ✅ | — | Dashboard address, e.g. `http://10.0.0.5:8080` |
| `INGEST_TOKEN` | | *(empty)* | Must match the dashboard |
| `LOG_PATH` | | `/var/log/nginx/api_access.log` | Active log file, as seen inside the container |
| `LOG_ROTATE_DIR` | | `/var/log/nginx/old` | logrotate archive directory (empty to skip) |
| `LOG_ROTATE_PATTERN` | | `api_access.log-*.gz` | Glob for rotated files (must contain an 8-digit date) |
| `CURSOR_FILE` | | `/agent/state/agent_cursor.json` | Read position, so restarts don't resend. **Put this on a volume.** |
| `NGINX_PLUS_API` | | *(empty)* | NGINX Plus REST API URL (empty to skip) |
| `POLL_INTERVAL` | | `30` | Seconds between polls |
| `BATCH_SIZE` | | `5000` | Maximum rows per request |
| `RETAIN_DAYS` | | `7` | Skip rotated logs older than this |
| `SKIP_ERROR_RESPONSES` | | `false` | Exclude 4xx/5xx responses |
| `AGENT_ID` | | hostname | Identifier shown in the dashboard |

- **Volumes**: `/var/log/nginx` (read-only), `/agent/state` (cursor persistence)
- **Log format**: JSON, one object per line. The `log_format` block to copy is on the [dashboard image page](https://hub.docker.com/r/gusgh13900/api-discovery-nginx).

---

## docker-compose

```bash
curl -O https://raw.githubusercontent.com/VEEP09/api-discovery-for-nginx/main/docker-compose.agent.yml
DASHBOARD_URL=http://<dashboard-host>:8080 INGEST_TOKEN=<token> \
  docker compose -f docker-compose.agent.yml up -d
```

Run this on your **NGINX host**, not on the dashboard host.

---

## Versions

| Tag | Description |
|-----|-------------|
| `latest` | Newest stable release (currently `1.2.1`) |
| `1.2.1` | No source changes; released alongside the dashboard. [Release notes](https://github.com/VEEP09/api-discovery-for-nginx/blob/main/releases/api-discovery-agent/v1.2.1.md) |
| `1.2.0` | English log output and `--help`. [Release notes](https://github.com/VEEP09/api-discovery-for-nginx/blob/main/releases/api-discovery-agent/v1.2.0.md) |
| `1.1.0` | Base image refresh, no source changes. [Release notes](https://github.com/VEEP09/api-discovery-for-nginx/blob/main/releases/api-discovery-agent/v1.1.0.md) |
| `1.0.0` | Initial release |

Pin a version tag in production rather than using `latest`, and keep the dashboard and agent on the **same tag**. Sizes above are compressed download sizes.

---

## Links

- 📖 [Project page and documentation](https://github.com/VEEP09/api-discovery-for-nginx)
- 📝 [Release notes](https://github.com/VEEP09/api-discovery-for-nginx/tree/main/releases)
- 📮 Bug reports, feature requests, enquiries: **gusgh13900@gmail.com**

---

# 한국어

## API Discovery for NGINX — 에이전트

**API Discovery for NGINX** 의 로그 수집 에이전트입니다. NGINX 서버에서 실행되며 액세스 로그(및 선택적으로 NGINX Plus REST API 지표)를 읽어 대시보드로 전송합니다.

> 🔗 **대시보드 이미지**: [`gusgh13900/api-discovery-nginx`](https://hub.docker.com/r/gusgh13900/api-discovery-nginx) — 수집 서버 + 웹 UI(`:8080`). **이 이미지와 동일한 버전 태그**로 맞춰 사용하세요.

| 이미지 | 역할 | 다운로드 | 디스크 | 실행 위치 |
|--------|------|----------|--------|-----------|
| **`api-discovery-agent`** (이 이미지) | NGINX 로그 수집 에이전트 | ~21 MB | ~56 MB | NGINX 서버 |
| `api-discovery-nginx` | 수집 서버 + 웹 대시보드 (`:8080`) | ~288 MB | ~1 GB | 대시보드 서버 |

- **소스**: **Apache-2.0** 오픈소스 — [github.com/VEEP09/api-discovery-for-nginx](https://github.com/VEEP09/api-discovery-for-nginx)
- **아키텍처**: `linux/amd64` (ARM 미지원)
- **설정**: 전부 **환경변수**로 주입합니다. 비밀값은 이미지에 포함되지 않습니다.
- **구성**: distroless 이미지로 셸이 없고 Python 의존성은 하나뿐입니다. 로그를 읽기 전용으로 읽어 전송하는 것 외에는 아무것도 하지 않습니다.

### 빠른 시작

먼저 [대시보드](https://hub.docker.com/r/gusgh13900/api-discovery-nginx)를 띄운 뒤, NGINX 서버에서 실행합니다.

```bash
docker run -d --name api-discovery-agent \
  --network host \
  -e DASHBOARD_URL=http://<대시보드-서버>:8080 \
  -e INGEST_TOKEN=<대시보드와 동일한 토큰> \
  -e LOG_PATH=/var/log/nginx/api_access.log \
  -e CURSOR_FILE=/agent/state/agent_cursor.json \
  -e NGINX_PLUS_API=http://127.0.0.1:411/api/9 \
  -v /var/log/nginx:/var/log/nginx:ro \
  -v $PWD/state:/agent/state \
  gusgh13900/api-discovery-agent:1.2.1
```

> **`INGEST_TOKEN` 은 양쪽이 반드시 동일해야 합니다.** 값이 다르면 에이전트는 정상 기동하고 로그에 `HTTP 401` 만 반복해서 찍으며 대시보드에는 끝내 나타나지 않습니다. 비워두면 인증이 완전히 비활성화되므로 로컬 전용으로만 쓰세요.

대시보드가 원격이고 NGINX Plus 메트릭을 수집하지 않는다면 `--network host` 는 빼도 됩니다.

### 환경변수

| 변수 | 필수 | 기본값 | 설명 |
|------|:---:|--------|------|
| `DASHBOARD_URL` | ✅ | — | 대시보드 주소 (예: `http://10.0.0.5:8080`) |
| `INGEST_TOKEN` | | *(빈 값)* | 대시보드와 동일해야 함 |
| `LOG_PATH` | | `/var/log/nginx/api_access.log` | 활성 로그 파일(컨테이너 내부 경로) |
| `LOG_ROTATE_DIR` | | `/var/log/nginx/old` | logrotate 보관 디렉토리 (빈 값이면 미수집) |
| `LOG_ROTATE_PATTERN` | | `api_access.log-*.gz` | rotated 파일 glob (날짜 8자리 포함 필요) |
| `CURSOR_FILE` | | `/agent/state/agent_cursor.json` | 읽기 위치 저장 — 재시작 시 중복 전송 방지. **볼륨 경로로 지정하세요.** |
| `NGINX_PLUS_API` | | *(빈 값)* | NGINX Plus REST API URL (빈 값이면 미수집) |
| `POLL_INTERVAL` | | `30` | 폴링 주기(초) |
| `BATCH_SIZE` | | `5000` | 1회 전송 최대 행 수 |
| `RETAIN_DAYS` | | `7` | 이 기간보다 오래된 rotated 로그는 건너뜀 |
| `SKIP_ERROR_RESPONSES` | | `false` | 4xx/5xx 응답 제외 여부 |
| `AGENT_ID` | | 호스트명 | 대시보드에 표시될 식별자 |

- **볼륨**: `/var/log/nginx`(읽기 전용), `/agent/state`(커서 영속화)
- **로그 포맷**: JSON, 한 줄에 객체 하나. 복사할 `log_format` 블록은 [대시보드 이미지 페이지](https://hub.docker.com/r/gusgh13900/api-discovery-nginx)에 있습니다.

### docker-compose

```bash
curl -O https://raw.githubusercontent.com/VEEP09/api-discovery-for-nginx/main/docker-compose.agent.yml
DASHBOARD_URL=http://<대시보드-서버>:8080 INGEST_TOKEN=<토큰> \
  docker compose -f docker-compose.agent.yml up -d
```

대시보드 서버가 아니라 **NGINX 서버**에서 실행하세요.

### 버전

| 태그 | 설명 |
|------|------|
| `latest` | 최신 안정 버전 (현재 `1.2.1`) |
| `1.2.1` | 소스 변경 없음, 대시보드와 함께 배포. [릴리스 노트](https://github.com/VEEP09/api-discovery-for-nginx/blob/main/releases/api-discovery-agent/v1.2.1.md) |
| `1.2.0` | 로그 출력·`--help` 영문화. [릴리스 노트](https://github.com/VEEP09/api-discovery-for-nginx/blob/main/releases/api-discovery-agent/v1.2.0.md) |
| `1.1.0` | 베이스 이미지 갱신, 소스 변경 없음. [릴리스 노트](https://github.com/VEEP09/api-discovery-for-nginx/blob/main/releases/api-discovery-agent/v1.1.0.md) |
| `1.0.0` | 최초 릴리스 |

프로덕션에서는 `latest` 대신 고정 버전 태그를 쓰고, 대시보드와 에이전트를 **같은 태그**로 맞추세요. 위 크기는 압축된 다운로드 기준입니다.

### 링크

- 📖 [프로젝트 페이지 · 문서](https://github.com/VEEP09/api-discovery-for-nginx)
- 📝 [릴리스 노트](https://github.com/VEEP09/api-discovery-for-nginx/tree/main/releases)
- 📮 버그 제보 · 기능 제안 · 도입 문의: **gusgh13900@gmail.com**

---

<sub>NGINX® is a registered trademark of F5, Inc. This project is an independent tool and is **not affiliated with, endorsed by, or sponsored by** F5 or NGINX. "NGINX" is used here only to describe compatibility.</sub>

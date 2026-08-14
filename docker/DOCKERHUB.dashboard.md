# API Discovery for NGINX — Dashboard

> 🇰🇷 **한국어 문서는 이 페이지 아래쪽에 있습니다.** · Korean documentation follows below.

**Find every API endpoint behind your NGINX — including the ones nobody documented.**

This image reads your existing **NGINX / NGINX Plus access logs** and turns them into a live API inventory: which endpoints actually receive traffic, which ones are missing from your OpenAPI spec (**shadow APIs**), which ones answer without an `Authorization` header, and which ones are behaving abnormally. No application changes, no instrumentation, no SDK.

This is the **collector server + web dashboard** (`:8080`). It needs a **collection agent** to send it logs:

> 🔗 **Agent image**: [`gusgh13900/api-discovery-agent`](https://hub.docker.com/r/gusgh13900/api-discovery-agent) — runs on your NGINX host. Keep it on the **same version tag** as this image.

| Image | Role | Download | On disk | Runs on |
|-------|------|----------|---------|---------|
| **`api-discovery-nginx`** (this image) | Collector server + web dashboard (`:8080`) | ~288 MB | ~1 GB | Dashboard host |
| `api-discovery-agent` | NGINX log collector | ~21 MB | ~56 MB | NGINX host |

- **Architecture**: `linux/amd64` (no ARM build)
- **Configuration**: entirely through **environment variables**. No config file to mount — pull and run. Secrets are never baked into the image.

---

## Quick start

```bash
docker run -d --name api-discovery-nginx \
  -p 8080:8080 \
  -e INGEST_TOKEN=<a shared secret you choose> \
  -v $PWD/output:/app/output \
  gusgh13900/api-discovery-nginx:1.2.1
```

Open `http://<dashboard-host>:8080`.

> ⚠️ **Change the default password.** The dashboard requires a session login and creates a default administrator **`admin` / `admin1234`** on first start. Log in and change it immediately. Accounts live in `output/auth_users.json` on your volume, so they survive restarts and upgrades.

Then deploy [`gusgh13900/api-discovery-agent`](https://hub.docker.com/r/gusgh13900/api-discovery-agent) on your NGINX host with the **same `INGEST_TOKEN`**. Data starts arriving within one poll interval (30s by default).

If the dashboard shows *"no agent connected"*, the cause is almost always an `INGEST_TOKEN` that does not match on both sides.

---

## What you get

- **Automatic API inventory** — path parameters are normalized (`/users/{id}`, `/orders/{uuid}`) so raw URIs collapse into real endpoints.
- **Shadow API detection** — endpoints receiving live traffic that are absent from your OpenAPI spec.
- **ML / DL anomaly detection** — autoencoder + LSTM models flag abnormal traffic patterns.
- **Off-hours and suspicious-IP detection**.
- **Latency percentiles** — p50 / p95 / p99 per endpoint.
- **Unauthenticated endpoint flagging** — endpoints served without an `Authorization` header.
- **OpenAPI export** — download the discovered surface as a spec.
- **Try Request** — replay a discovered endpoint from the UI.
- **Connected agents view** — health and last-seen for every agent.
- **NGINX Plus metrics** — optional, when the Plus REST API is reachable.
- **Session login + RBAC** — `admin` and `viewer` roles.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `INGEST_TOKEN` | *(empty)* | Shared secret the agent must present. **Leaving it empty disables authentication on `/api/ingest`** — only acceptable on a trusted local network. |
| `DASHBOARD_SECRET` | *(generated)* | Session cookie signing key. Generated into `output/auth_secret` if unset. Set explicitly if you run more than one instance. |

- **Port**: `8080` (fixed inside the container)
- **Volume**: `/app/output` — SQLite database, analysis results, trained models, user accounts, signing key
- **Health check**: `GET /healthz`

---

## docker-compose

```bash
curl -O https://raw.githubusercontent.com/VEEP09/api-discovery-for-nginx/main/docker-compose.yml
INGEST_TOKEN=<token> docker compose up -d
```

The agent has its own compose file — see the [agent image page](https://hub.docker.com/r/gusgh13900/api-discovery-agent). Run it on your NGINX host, not here.

---

## Required NGINX log format

The agent expects a JSON access log. Add this to your NGINX configuration:

```nginx
# /etc/nginx/nginx.conf
http {
     log_format api_discovery escape=json
     '{'
         '"time":"$time_iso8601",'
         '"remote_addr":"$remote_addr",'
         '"method":"$request_method",'
         '"uri":"$uri",'
         '"query_string":"$query_string",'
         '"status":$status,'
         '"body_bytes_sent":$body_bytes_sent,'
         '"request_length":$request_length,'
         '"request_time":$request_time,'
         '"http_user_agent":"$http_user_agent",'
         '"http_referer":"$http_referer",'
         '"http_x_forwarded_for":"$http_x_forwarded_for",'
         '"http_authorization":"$http_authorization",'
         '"http_content_type":"$http_content_type",'
         '"http_accept":"$http_accept",'
         '"upstream_response_time":"$upstream_response_time",'
         '"host":"$host",'
         '"request_id":"$request_id"'
     '}';

    access_log /var/log/nginx/api_access.log api_discovery;
}
```

Works with **open-source NGINX**. NGINX Plus is optional and only adds the extra REST API metrics.

---

## Versions

| Tag | Description |
|-----|-------------|
| `latest` | Newest stable release (currently `1.2.1`) |
| `1.2.1` | Fixes for the EN/KO switcher (help icons, re-render, 81 unkeyed strings). [Release notes](https://github.com/VEEP09/api-discovery-for-nginx/blob/main/releases/api-discovery-nginx/v1.2.1.md) |
| `1.2.0` | English interface with an EN/KO switcher. [Release notes](https://github.com/VEEP09/api-discovery-for-nginx/blob/main/releases/api-discovery-nginx/v1.2.0.md) |
| `1.1.0` | ~288 MB to pull, down from ~2.8 GB. [Release notes](https://github.com/VEEP09/api-discovery-for-nginx/blob/main/releases/api-discovery-nginx/v1.1.0.md) |
| `1.0.0` | Initial release (~2.8 GB — superseded, use `1.1.0`) |

Pin a version tag in production rather than using `latest`, and keep the dashboard and agent on the **same tag**. Sizes above are compressed download sizes.

---

## Links

- 📖 [Project page and documentation](https://github.com/VEEP09/api-discovery-for-nginx)
- 📝 [Release notes](https://github.com/VEEP09/api-discovery-for-nginx/tree/main/releases)
- 📮 Bug reports, feature requests, enquiries: **gusgh13900@gmail.com**

---

# 한국어

## API Discovery for NGINX — 대시보드

**NGINX 뒤에 실제로 살아 있는 API를 전부 찾아냅니다 — 아무도 문서화하지 않은 것까지.**

이미 쌓이고 있는 **NGINX / NGINX Plus 액세스 로그**를 읽어 실시간 API 인벤토리를 구성합니다. 어떤 엔드포인트에 실제 트래픽이 오는지, OpenAPI 스펙에 없는 엔드포인트(**Shadow API**)는 무엇인지, `Authorization` 헤더 없이 응답하는 엔드포인트는 어디인지, 평소와 다르게 동작하는 것은 무엇인지를 보여줍니다. 애플리케이션 수정도, 계측 코드도, SDK도 필요 없습니다.

이 이미지는 **수집 서버 + 웹 대시보드(`:8080`)** 입니다. 로그를 보내줄 **수집 에이전트**가 함께 필요합니다.

> 🔗 **에이전트 이미지**: [`gusgh13900/api-discovery-agent`](https://hub.docker.com/r/gusgh13900/api-discovery-agent) — NGINX 서버에서 실행. **이 이미지와 동일한 버전 태그**로 맞춰 사용하세요.

| 이미지 | 역할 | 다운로드 | 디스크 | 실행 위치 |
|--------|------|----------|--------|-----------|
| **`api-discovery-nginx`** (이 이미지) | 수집 서버 + 웹 대시보드 (`:8080`) | ~288 MB | ~1 GB | 대시보드 서버 |
| `api-discovery-agent` | NGINX 로그 수집 에이전트 | ~21 MB | ~56 MB | NGINX 서버 |

- **아키텍처**: `linux/amd64` (ARM 미지원)
- **설정**: 전부 **환경변수**로 주입합니다. 설정 파일 마운트 없이 pull 후 바로 실행할 수 있고, 비밀값은 이미지에 포함되지 않습니다.

### 빠른 시작

```bash
docker run -d --name api-discovery-nginx \
  -p 8080:8080 \
  -e INGEST_TOKEN=<직접 정한 공유 토큰> \
  -v $PWD/output:/app/output \
  gusgh13900/api-discovery-nginx:1.2.1
```

브라우저에서 `http://<대시보드-서버>:8080` 접속.

> ⚠️ **기본 비밀번호를 반드시 변경하세요.** 대시보드는 세션 로그인이 필요하며 최초 기동 시 기본 관리자 **`admin` / `admin1234`** 가 생성됩니다. 로그인 후 즉시 변경하세요. 계정은 볼륨의 `output/auth_users.json` 에 저장되어 재시작·업그레이드에도 유지됩니다.

이후 [`gusgh13900/api-discovery-agent`](https://hub.docker.com/r/gusgh13900/api-discovery-agent) 를 NGINX 서버에 **동일한 `INGEST_TOKEN`** 으로 띄우면 폴링 주기(기본 30초) 내에 데이터가 들어오기 시작합니다.

대시보드에 *"에이전트가 연결되지 않았습니다"* 가 계속 보인다면, 원인은 대부분 양쪽 `INGEST_TOKEN` 불일치입니다.

### 주요 기능

- **API 인벤토리 자동 구성** — 경로 파라미터를 정규화(`/users/{id}`, `/orders/{uuid}`)해 원시 URI를 실제 엔드포인트 단위로 묶습니다.
- **Shadow API 탐지** — 트래픽은 들어오는데 OpenAPI 스펙에는 없는 엔드포인트를 찾아냅니다.
- **ML / DL 이상 탐지** — AutoEncoder + LSTM 모델이 비정상 트래픽 패턴을 표시합니다.
- **Off-hour 탐지 · Suspicious IP 탐지**
- **레이턴시 백분위** — 엔드포인트별 p50 / p95 / p99
- **무인증 엔드포인트 표시** — `Authorization` 헤더 없이 응답하는 엔드포인트
- **OpenAPI export** — 탐지된 API 표면을 스펙으로 내려받기
- **Try Request** — 탐지된 엔드포인트를 UI에서 바로 호출
- **Connected Agents** — 에이전트별 상태와 마지막 수신 시각
- **NGINX Plus 메트릭** — Plus REST API 접근 가능 시 선택적으로 수집
- **세션 로그인 + RBAC** — `admin` / `viewer` 역할

### 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `INGEST_TOKEN` | *(빈 값)* | 에이전트가 제시해야 하는 공유 토큰. **비우면 `/api/ingest` 인증이 비활성화됩니다** — 신뢰된 내부망에서만 사용하세요. |
| `DASHBOARD_SECRET` | *(자동 생성)* | 세션 쿠키 서명키. 미지정 시 `output/auth_secret` 에 생성·보존. 인스턴스를 여러 개 운영하면 명시적으로 지정하세요. |

- **포트**: `8080` (컨테이너 내부 고정)
- **볼륨**: `/app/output` — SQLite DB, 분석 결과, 학습된 모델, 계정, 서명키
- **헬스체크**: `GET /healthz`

### docker-compose

```bash
curl -O https://raw.githubusercontent.com/VEEP09/api-discovery-for-nginx/main/docker-compose.yml
INGEST_TOKEN=<토큰> docker compose up -d
```

에이전트는 별도 compose 파일을 사용합니다 — [에이전트 이미지 페이지](https://hub.docker.com/r/gusgh13900/api-discovery-agent) 참고. NGINX 서버에서 실행하세요.

### NGINX 로그 포맷

에이전트는 JSON 액세스 로그를 전제로 합니다. 위 영문 섹션의 `log_format api_discovery` 블록을 NGINX 설정에 추가하고 `access_log` 를 지정하세요.

**오픈소스 NGINX에서 동작합니다.** NGINX Plus는 선택이며 REST API 메트릭이 추가될 뿐입니다.

### 버전

| 태그 | 설명 |
|------|------|
| `latest` | 최신 안정 버전 (현재 `1.2.1`) |
| `1.2.1` | 언어 전환 결함 수정 (도움말 아이콘·재렌더·미부여 키 81건). [릴리스 노트](https://github.com/VEEP09/api-discovery-for-nginx/blob/main/releases/api-discovery-nginx/v1.2.1.md) |
| `1.2.0` | 영어 UI + EN/KO 언어 전환. [릴리스 노트](https://github.com/VEEP09/api-discovery-for-nginx/blob/main/releases/api-discovery-nginx/v1.2.0.md) |
| `1.1.0` | 다운로드 ~288 MB (기존 ~2.8 GB에서 축소). [릴리스 노트](https://github.com/VEEP09/api-discovery-for-nginx/blob/main/releases/api-discovery-nginx/v1.1.0.md) |
| `1.0.0` | 최초 릴리스 (~2.8 GB — `1.1.0` 사용 권장) |

프로덕션에서는 `latest` 대신 고정 버전 태그를 쓰고, 대시보드와 에이전트를 **같은 태그**로 맞추세요. 위 크기는 압축된 다운로드 기준입니다.

### 링크

- 📖 [프로젝트 페이지 · 문서](https://github.com/VEEP09/api-discovery-for-nginx)
- 📝 [릴리스 노트](https://github.com/VEEP09/api-discovery-for-nginx/tree/main/releases)
- 📮 버그 제보 · 기능 제안 · 도입 문의: **gusgh13900@gmail.com**

---

<sub>NGINX® is a registered trademark of F5, Inc. This project is an independent tool and is **not affiliated with, endorsed by, or sponsored by** F5 or NGINX. "NGINX" is used here only to describe compatibility.</sub>

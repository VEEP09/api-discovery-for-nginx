# Docker 배포 파일

이 디렉토리는 **Docker 전용** 설정을 모아둔 곳입니다. 기존의 직접 실행
방식(`make install` / `make start`, 에이전트 `install.sh` + systemd)과 구분됩니다.

```
docker/
├── dashboard/                 # Dashboard VM 용
│   ├── Dockerfile
│   ├── Dockerfile.dockerignore
│   └── docker-compose.yml
└── agent/                     # NGINX(Plus) VM 용
    ├── Dockerfile
    ├── Dockerfile.dockerignore
    └── docker-compose.yml
```

두 이미지는 독립적으로 빌드/실행합니다. 보통 **다른 VM**에서 각각 돌립니다.

## Dashboard

빌드 컨텍스트는 저장소 루트입니다.

```bash
# 저장소 루트에서
docker compose -f docker/dashboard/docker-compose.yml up -d --build
# 또는
make docker-build        # 루트 Makefile 이 위 compose 를 호출
```

- 포트 `8080` 노출, `../../output`(결과·SQLite DB)과 `../../config` 를 마운트.
- `Dockerfile.dockerignore` 로 `output/`(수 GB)·`.git`·가상환경을 이미지에서 제외.

## Agent

빌드 컨텍스트는 `agent/` 입니다. NGINX 로그를 읽어야 하므로 로그 디렉토리를
마운트하고, NGINX Plus API(localhost) 접근을 위해 host 네트워크를 사용합니다.

```bash
# NGINX VM 에서 (저장소를 clone 한 뒤)
vi agent/agent_config.yaml          # dashboard_url, ingest_token, cursor_file 등 설정
mkdir -p agent/state                # 커서 영속화용
docker compose -f docker/agent/docker-compose.yml up -d --build
```

### Agent 설정 시 주의

| 항목 | 값 |
|------|----|
| `cursor_file` | `/agent/state/agent_cursor.json` (볼륨 경로여야 재시작 시 중복 전송 방지) |
| `log_path` | `/var/log/nginx/api_access.log` (마운트된 컨테이너 내부 경로) |
| `nginx_plus_api` | host 네트워크이므로 `http://127.0.0.1:411/api/9` 그대로 사용 가능 |

대시보드가 원격이고 NGINX Plus 메트릭을 쓰지 않으면 compose 의
`network_mode: host` 를 지우고 기본 bridge 로 실행해도 됩니다.

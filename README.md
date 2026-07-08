# API Discovery for NGINX

> **Automatically discover every API endpoint behind your NGINX / NGINX Plus.** Detect **shadow APIs**, build a live **API inventory**, and catch anomalies with machine learning — all from your existing access logs. Self-hosted, Docker-ready, no code changes.

[![Dashboard pulls](https://img.shields.io/docker/pulls/gusgh13900/api-discovery-nginx?label=dashboard%20pulls&logo=docker)](https://hub.docker.com/r/gusgh13900/api-discovery-nginx)
[![Agent pulls](https://img.shields.io/docker/pulls/gusgh13900/api-discovery-agent?label=agent%20pulls&logo=docker)](https://hub.docker.com/r/gusgh13900/api-discovery-agent)
[![Dashboard image size](https://img.shields.io/docker/image-size/gusgh13900/api-discovery-nginx/latest?label=dashboard%20size)](https://hub.docker.com/r/gusgh13900/api-discovery-nginx)

**API Discovery for NGINX** turns raw **NGINX access logs** into a real-time **API observability** dashboard. It answers the question every platform and security team eventually asks: *“What APIs are actually running behind our NGINX?”* — including undocumented **shadow APIs** and forgotten **zombie endpoints** — without instrumenting your application or changing a single line of code.

---

## Screenshots
<img width="647" height="45" alt="image" src="https://github.com/user-attachments/assets/7bae92a0-baa1-4ecd-804b-64a5231638b6" />
<img width="1472" height="732" alt="image" src="https://github.com/user-attachments/assets/8ea890ae-ffe8-49a5-baae-210f17200eab" />
<img width="1477" height="547" alt="image" src="https://github.com/user-attachments/assets/ec04b2a3-4f5f-4ca5-aca4-287b206943ff" />
<img width="1476" height="553" alt="image" src="https://github.com/user-attachments/assets/2f84f841-b119-4145-84e4-926e7c14541c" />

The actual service shows more information than the screenshots.

<!-- Add PNGs to docs/screenshots/ and uncomment — screenshots are the #1 driver of clicks:
![API inventory dashboard](docs/screenshots/dashboard.png)
![Endpoint detail with latency percentiles](docs/screenshots/endpoints.png)
-->


---

## Features

- 🔎 **Automatic API inventory** — path-parameter normalization (`/users/{id}`, `/orders/{uuid}`) groups raw URIs into real endpoints.
- 🕵️ **Shadow API detection** — surface endpoints that receive traffic but aren't in your OpenAPI spec.
- 📊 **Latency percentiles** — p50 / p95 / p99 per endpoint, plus slowest-endpoint ranking.
- 🧠 **ML / DL anomaly detection** — autoencoder + LSTM models flag abnormal traffic and behavior.
- 🔓 **No-auth endpoint flagging** — spot endpoints served without an `Authorization` header.
- 🔐 **Session login + RBAC** — built-in `admin` / `viewer` roles.
- 📤 **OpenAPI export** — download the discovered surface as an OpenAPI spec.
- 🐳 **Two small Docker images** — env-var configuration, no config files, no app changes.

---

## How it works

```
┌──────────────────────┐        JSON access logs         ┌───────────────────────────┐
│  Agent                │  ───────────────────────────▶  │  Dashboard                │
│  (on your NGINX host) │        (HTTPS, token auth)      │  collector + web UI :8080 │
│  api-discovery-agent  │                                 │  api-discovery-nginx      │
└──────────────────────┘                                 └───────────────────────────┘
```

The **agent** tails your NGINX access log (and optionally the NGINX Plus REST API) and ships records to the **dashboard**, which aggregates them into an API inventory, runs anomaly detection, and serves the web UI.

---

## Quick start

### 1) Dashboard (on a server you can reach)

```bash
docker run -d --name api-discovery-nginx \
  -p 8080:8080 \
  -e INGEST_TOKEN=<shared-token> \
  -v $PWD/output:/app/output \
  gusgh13900/api-discovery-nginx:latest
```

Open `http://<host>:8080` and log in with the default admin account **`admin` / `admin1234`** (change it immediately under the **Users** tab).

### 2) Agent (on your NGINX / NGINX Plus host)

```bash
docker run -d --name api-discovery-agent \
  --network host \
  -e DASHBOARD_URL=http://<dashboard-host>:8080 \
  -e INGEST_TOKEN=<same-token-as-above> \
  -e LOG_PATH=/var/log/nginx/api_access.log \
  -v /var/log/nginx:/var/log/nginx:ro \
  -v $PWD/state:/agent/state \
  gusgh13900/api-discovery-agent:latest
```

### docker-compose

The dashboard and agent run on **different hosts**, so there are two compose files:

```bash
# On the dashboard host
INGEST_TOKEN=<shared-token> docker compose -f docker-compose.yml up -d

# On the NGINX host
DASHBOARD_URL=http://<dashboard-host>:8080 INGEST_TOKEN=<shared-token> \
  docker compose -f docker-compose.agent.yml up -d
```

---

## Docker images

| Image | Role | Size |
|-------|------|------|
| [`gusgh13900/api-discovery-nginx`](https://hub.docker.com/r/gusgh13900/api-discovery-nginx) | Collector server + web dashboard (`:8080`) | ~5 GB (bundles PyTorch) |
| [`gusgh13900/api-discovery-agent`](https://hub.docker.com/r/gusgh13900/api-discovery-agent) | NGINX log-collecting agent | ~56 MB |

Both images are `linux/amd64` and published with `latest` and pinned version tags (e.g. `1.0.0`). Keep the dashboard and agent on the **same version tag**.

---

## Requirements

- **NGINX or NGINX Plus** producing a JSON access log (a ready-to-copy `log_format` block is shown on the dashboard image page).
- **Docker** on both the dashboard host and the NGINX host.
- Works with **open-source NGINX** — NGINX Plus is optional (only needed for the extra REST API metrics).

---

## Use cases

- **API security** — find shadow / undocumented / zombie APIs that expand your attack surface.
- **Platform & SRE** — a live, always-current inventory of every service behind the gateway.
- **API governance** — compare real traffic against your OpenAPI spec and export the delta.
- **Performance** — spot the slowest endpoints (p95 / p99) without adding APM agents.

---

## FAQ

**Do I need NGINX Plus?** No. It works with open-source NGINX. NGINX Plus only adds optional upstream metrics.

**Does it modify my application?** No. It reads access logs only — zero code changes, zero request-path overhead.

**Does it support ARM?** Currently `linux/amd64` only.

**Where is data stored?** In the dashboard's `/app/output` volume (SQLite + analysis results + accounts). Mount it to persist across restarts.

---

## Login & roles

The dashboard requires a session login. On first start a default admin **`admin` / `admin1234`** is created automatically — **change the password after first login**. Roles are **admin** (full access) and **viewer** (read-only); accounts are managed in the **Users** tab and persist in the `output/` volume.

---

## License

This is **commercial / proprietary software**. Use is permitted (including commercial use); redistribution, modification, reselling, and sublicensing are not. See the image pages for terms, or contact the author below.

## Contact

Bug reports · feature requests · deployment questions: **gusgh13900@gmail.com**

---

<sub>NGINX® is a registered trademark of F5, Inc. This is an independent project and is **not affiliated with, endorsed by, or sponsored by** F5 or NGINX. The name “NGINX” is used only to describe compatibility.</sub>

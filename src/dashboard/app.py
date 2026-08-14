"""
FastAPI 대시보드 서버.
대시보드 UI는 /  에서 제공, 데이터 API는 /api/* 에서 제공.
로그 수집은 nginx-apigent가 담당하며 /api/ingest 로 수신한다.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import sys
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
import yaml
from fastapi import BackgroundTasks, Body, FastAPI, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.dashboard import auth
from src.dashboard.reader import OutputReader
from src.discovery.openapi_generator import build_full_spec, merge_shadow_endpoints
from src.discovery.openapi_parser import parse_spec

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent

KST = ZoneInfo("Asia/Seoul")

_reader: OutputReader = None
_config_path: str = "config/settings.yaml"

# 파이프라인 실행 상태
_pipeline = {
    "running": False,
    "last_run_at": None,
    "last_run_ok": None,
    "last_error": None,
    "last_trigger": None,     # "manual" | "daily"
}

# 에이전트 연결 상태 (agent_id → 메타)
_agents: dict = {}
_agents_lock = threading.Lock()


def _record_agent(agent_id: str, ip: str, poll_interval: int, rows: int,
                   nginx_status: str = "unknown", nginx_plus: dict = None,
                   nginx_edition: str = "unknown"):
    now = datetime.now(KST)
    # 식별키 = agent_id + IP. 두 VM의 호스트네임이 같아도 IP가 다르면 별도 카드로
    # 유지된다 (IP만으로는 NAT/도커 게이트웨이 공유 시 오히려 합쳐지므로 복합키 사용).
    key = f"{agent_id}@{ip}"
    with _agents_lock:
        prev = _agents.get(key, {"total_rows": 0})
        entry = {
            "agent_id":     agent_id,
            "ip":           ip,
            "last_seen":    now.isoformat(timespec="seconds"),
            "last_seen_ts": now.timestamp(),
            "poll_interval": poll_interval,
            "total_rows":   prev["total_rows"] + rows,
            "nginx_status": nginx_status,
            # 종류(plus/oss)는 매 보고마다 안 올 수 있으니 이전 값을 유지한다.
            "nginx_edition": nginx_edition if nginx_edition and nginx_edition != "unknown"
                             else prev.get("nginx_edition", "unknown"),
        }
        if nginx_plus:
            entry["nginx_plus"] = nginx_plus
        elif "nginx_plus" in prev:
            entry["nginx_plus"] = prev["nginx_plus"]  # 이전 값 유지
        _agents[key] = entry


def _agent_status(last_seen_ts: float, poll_interval: int) -> str:
    elapsed = time.time() - last_seen_ts
    if elapsed < poll_interval * 3:
        return "online"
    if elapsed < 300:
        return "unknown"
    return "offline"


def init_reader(output_dir: str):
    global _reader
    _reader = OutputReader(output_dir)


def init_config(config_path: str):
    global _config_path, _auth_cfg
    _config_path = config_path
    _auth_cfg = None  # 다음 요청에서 새 경로로 재로딩


# ── 인증 (세션 로그인 + admin/viewer RBAC) ──────────────

_auth_cfg = None


def _get_auth() -> dict:
    """auth 설정을 lazy 로드·캐시. init_config/계정 변경 시 캐시를 무효화한다."""
    global _auth_cfg
    if _auth_cfg is None:
        _auth_cfg = auth.load_auth_config(_config_path, str(get_reader().output_dir))
    return _auth_cfg


def _invalidate_auth():
    global _auth_cfg
    _auth_cfg = None


# 세션 검사에서 제외할 경로. /api/ingest는 자체 Bearer 토큰으로 인증한다.
_AUTH_PUBLIC = {"/login", "/logout", "/healthz", "/favicon.ico", "/api/ingest"}

# GET이지만 admin만 허용할 경로 (전체 스펙 다운로드, 계정 목록 등).
_ADMIN_GET_PATHS = {"/api/openapi/export-all", "/api/users"}

_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{2,32}$")


def _current_user(request: Request):
    return getattr(request.state, "user", None)


def get_reader() -> OutputReader:
    if _reader is None:
        raise RuntimeError("init_reader() must be called first.")
    return _reader


# ── 백그라운드 트리거 ────────────────────────────────────────

async def _daily_trigger():
    """매일 KST 06:00에 파이프라인을 자동 실행한다."""
    while True:
        now = datetime.now(KST)
        next_run = now.replace(hour=6, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run += timedelta(days=1)
        sleep_secs = (next_run - now).total_seconds()
        logger.info(f"[daily] Next run: {next_run.strftime('%Y-%m-%d %H:%M KST')} (in {sleep_secs/3600:.1f}h)")
        await asyncio.sleep(sleep_secs)
        if not _pipeline["running"]:
            logger.info("[daily] 06:00 KST trigger - starting pipeline")
            asyncio.create_task(_run_pipeline_task(trigger="daily"))
        else:
            logger.info("[daily] 06:00 KST reached but a pipeline is already running - skipped")


async def _run_pipeline_task(trigger: str = "manual", inventory_only: bool = False):
    """파이프라인을 서브프로세스로 실행. 완료 시 _pipeline 상태 갱신.

    inventory_only=True 이면 Inventory(데이터)만 갱신하고 딥러닝 학습은 건너뛴다.
    수동 'Run Now'는 데이터만 빠르게 갱신하고, 모델 재학습은 daily 스케줄에서 한다.
    """
    _pipeline["running"] = True
    _pipeline["last_run_at"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")
    _pipeline["last_trigger"] = trigger
    _pipeline["last_error"] = None
    logger.info(f"Pipeline started (trigger={trigger}, inventory_only={inventory_only})")
    try:
        cmd = [sys.executable, "main.py", "--config", _config_path]
        if inventory_only:
            cmd.append("--inventory-only")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode == 0:
            _pipeline["last_run_ok"] = True
            logger.info(f"Pipeline finished (trigger={trigger})")
        else:
            _pipeline["last_run_ok"] = False
            _pipeline["last_error"] = stderr.decode(errors="replace")[-800:].strip()
            logger.error(f"Pipeline failed (trigger={trigger}): {_pipeline['last_error']}")
    except Exception as e:
        _pipeline["last_run_ok"] = False
        _pipeline["last_error"] = str(e)
        logger.exception(f"Unhandled exception while running pipeline (trigger={trigger})")
    finally:
        _pipeline["running"] = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_daily_trigger())
    logger.info("Background scheduler started: daily at 06:00 KST")
    yield


app = FastAPI(title="NGINX API Discovery Dashboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ── 인증 미들웨어 ───────────────────────────────────────
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    request.state.user = None
    ac = _get_auth()
    if not ac["enabled"]:
        return await call_next(request)  # 로컬 모드: 인증 비활성

    path = request.url.path
    if path in _AUTH_PUBLIC or path.startswith("/static/"):
        return await call_next(request)

    user = auth.verify_session(request.cookies.get(auth.COOKIE_NAME, ""), ac["secret"])
    if not user:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "login required"}, status_code=401)
        return RedirectResponse(url="/login", status_code=302)

    request.state.user = user
    # 변경 요청(POST/PUT/DELETE/PATCH)은 admin 전용. GET 조회는 viewer 허용하되,
    # 전체 스펙 다운로드처럼 명시된 GET 경로는 admin 전용.
    is_mutating = request.method not in ("GET", "HEAD", "OPTIONS")
    if (is_mutating or path in _ADMIN_GET_PATHS) and user.get("role") != "admin":
        return JSONResponse({"detail": "Administrator privileges are required."}, status_code=403)
    return await call_next(request)


# ── 로그인 / 로그아웃 / 현재 사용자 ─────────────────────
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    ac = _get_auth()
    if not ac["enabled"]:
        return RedirectResponse(url="/", status_code=302)
    if auth.verify_session(request.cookies.get(auth.COOKIE_NAME, ""), ac["secret"]):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request,
                       username: str = Form(...), password: str = Form(...)):
    ac = _get_auth()
    if not ac["enabled"]:
        return RedirectResponse(url="/", status_code=302)
    u = ac["users"].get(username)
    if not u or not auth.verify_password(password, u["password_hash"]):
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "Incorrect username or password."},
            status_code=401,
        )
    token = auth.make_session(username, u["role"], ac["secret"], ac["session_seconds"])
    resp = RedirectResponse(url="/", status_code=302)
    resp.set_cookie(auth.COOKIE_NAME, token, max_age=ac["session_seconds"],
                    httponly=True, samesite="lax", path="/")
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie(auth.COOKIE_NAME, path="/")
    return resp


@app.get("/api/me")
async def api_me(request: Request):
    ac = _get_auth()
    if not ac["enabled"]:
        # 로컬 모드: 로그인 없이 전권(admin) — 관리 UI 그대로 노출
        return {"auth_enabled": False, "username": None, "role": "admin"}
    user = _current_user(request)
    return {
        "auth_enabled": True,
        "username": user["username"] if user else None,
        "role": user["role"] if user else None,
    }


# ── 계정 관리 (admin 전용; POST/DELETE는 미들웨어가, GET은 _ADMIN_GET_PATHS가 강제) ──

@app.get("/api/users")
async def api_users_list():
    return auth.list_users(str(get_reader().output_dir))


@app.post("/api/users")
async def api_users_create(payload: dict = Body(...)):
    username = (payload.get("username") or "").strip()
    role = payload.get("role")
    password = payload.get("password") or ""
    if not _USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail="Username must be 2-32 characters of letters, digits, dot, underscore or hyphen.")
    if role not in ("admin", "viewer"):
        raise HTTPException(status_code=400, detail="Role must be either admin or viewer.")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    od = str(get_reader().output_dir)
    if username in _get_auth()["users"]:
        raise HTTPException(status_code=409, detail="That username already exists.")
    auth.add_user(od, username, role, password)
    _invalidate_auth()
    return {"ok": True}


@app.delete("/api/users/{username}")
async def api_users_delete(username: str):
    od = str(get_reader().output_dir)
    managed = auth.load_managed_users(od)
    if username not in managed:
        raise HTTPException(status_code=404, detail="No such account, or it cannot be managed.")
    admins = [n for n, u in _get_auth()["users"].items() if u["role"] == "admin"]
    if managed[username]["role"] == "admin" and len(admins) <= 1:
        raise HTTPException(status_code=400, detail="The last administrator account cannot be deleted.")
    auth.delete_user(od, username)
    _invalidate_auth()
    return {"ok": True}


@app.post("/api/users/{username}/password")
async def api_users_set_password(username: str, payload: dict = Body(...)):
    password = payload.get("password") or ""
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    od = str(get_reader().output_dir)
    if not auth.set_password(od, username, password):
        raise HTTPException(status_code=404, detail="That account cannot be managed.")
    _invalidate_auth()
    return {"ok": True}


# ── HTML ────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "index.html")


# ── Health ──────────────────────────────────────────────

@app.get("/healthz")
async def healthz():
    """경량 헬스체크 — DB/분석 조회 없이 프로세스 생존만 확인."""
    return {"status": "ok"}


# ── Summary / Inventory ─────────────────────────────────

@app.get("/api/summary")
def api_summary():
    return get_reader().summary()


@app.get("/api/inventory")
def api_inventory(
    method: str = "",
    search: str = "",
    sort: str = "call_count",
    order: str = "desc",
):
    data = get_reader().get_inventory(attach_samples=True)
    if method:
        data = [e for e in data if e.get("method", "").upper() == method.upper()]
    if search:
        data = [e for e in data if search.lower() in e.get("endpoint", "").lower()]
    reverse = order == "desc"
    data.sort(key=lambda x: x.get(sort, 0), reverse=reverse)
    return data


# ── Charts ──────────────────────────────────────────────

@app.get("/api/charts/top-endpoints")
async def chart_top_endpoints(limit: int = 10):
    data = get_reader().get_inventory()
    top = sorted(data, key=lambda x: x.get("call_count", 0), reverse=True)[:limit]
    return [
        {"label": f"{e['method']} {e['endpoint']}", "value": e["call_count"]}
        for e in top
    ]


@app.get("/api/charts/method-dist")
async def chart_method_dist():
    from collections import Counter
    data = get_reader().get_inventory()
    counter = Counter(e.get("method") for e in data)
    return [{"label": k, "value": v} for k, v in counter.most_common()]


@app.get("/api/charts/status-dist")
async def chart_status_dist():
    data = get_reader().get_inventory()
    buckets = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
    for e in data:
        buckets["2xx"] += e.get("status_2xx", 0)
        buckets["4xx"] += e.get("status_4xx", 0)
        buckets["5xx"] += e.get("status_5xx", 0)
    return [{"label": k, "value": v} for k, v in buckets.items() if v > 0]


@app.get("/api/charts/error-rate")
async def chart_error_rate(limit: int = 10):
    data = get_reader().get_inventory()
    risky = sorted(data, key=lambda x: x.get("error_rate", 0), reverse=True)[:limit]
    return [
        {"label": f"{e['method']} {e['endpoint']}", "value": e["error_rate"]}
        for e in risky if e.get("error_rate", 0) > 0
    ]


@app.get("/api/charts/training-history")
async def chart_training():
    ae = get_reader().get_ae_history()
    lstm = get_reader().get_lstm_history()
    return {"autoencoder": ae, "lstm": lstm}


# ── Anomalies ───────────────────────────────────────────

@app.get("/api/anomalies/shadow")
async def api_shadow():
    result = get_reader().get_shadow_result()
    return [
        {
            "method": s.method,
            "endpoint": s.endpoint,
            "source": s.source,
            "call_count": s.call_count,
            "error_rate": s.error_rate,
            "has_auth": s.has_auth,
            "unique_ip_count": s.unique_ip_count,
            "domains": s.domains,
            "first_seen": s.first_seen,
            "last_seen": s.last_seen,
        }
        for s in result.shadow_endpoints
    ]


@app.get("/api/anomalies/unused-spec")
async def api_unused_spec():
    result = get_reader().get_shadow_result()
    return [
        {
            "method": u.method,
            "path": u.path,
            "operation_id": u.operation_id,
            "summary": u.summary,
            "tags": u.tags,
        }
        for u in result.unused_endpoints
    ]


@app.get("/api/anomalies/no-auth")
async def api_no_auth():
    data = get_reader().get_inventory()
    return [e for e in data if not e.get("has_auth")]


@app.get("/api/anomalies/slow")
async def api_slow():
    """p95 응답시간이 높은 상위 엔드포인트. 소량 샘플 노이즈를 피하기 위해
    호출 10회 이상·p95>0인 것만 대상으로 하고 p95 내림차순 Top 10을 반환한다."""
    data = get_reader().get_inventory()
    slow = [
        e for e in data
        if (e.get("p95_response_time") or 0) > 0 and (e.get("call_count") or 0) >= 10
    ]
    slow.sort(key=lambda e: e.get("p95_response_time") or 0, reverse=True)
    return slow[:10]


@app.get("/api/anomalies/ml-endpoints")
async def api_ml_endpoints():
    return get_reader().get_ml_endpoints()


@app.get("/api/anomalies/suspicious-ips")
async def api_suspicious_ips():
    return get_reader().get_suspicious_ips()


@app.get("/api/anomalies/time-anomaly")
async def api_time_anomaly():
    return get_reader().get_time_anomalies()


# ── OpenAPI Spec ────────────────────────────────────────

@app.get("/api/openapi/status")
async def openapi_status():
    return get_reader().get_openapi_info()


@app.post("/api/openapi/upload")
async def openapi_upload(file: UploadFile = File(...)):
    name = file.filename or "spec"
    suffix = Path(name).suffix.lower()
    if suffix not in (".yaml", ".yml", ".json"):
        raise HTTPException(status_code=400, detail="Only YAML or JSON files can be uploaded.")

    reader = get_reader()
    reader.openapi_dir.mkdir(parents=True, exist_ok=True)

    for old in reader.openapi_dir.glob("*"):
        old.unlink()

    save_path = reader.openapi_dir / f"spec{suffix}"
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # 파싱 검증
    try:
        spec = parse_spec(str(save_path))
    except Exception as e:
        save_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Failed to parse the spec: {e}")

    logger.info(f"OpenAPI spec uploaded: {spec.title} v{spec.version} ({spec.endpoint_count} endpoints)")
    return {
        "ok": True,
        "title": spec.title,
        "version": spec.version,
        "openapi_version": spec.openapi_version,
        "endpoint_count": spec.endpoint_count,
        "file_name": save_path.name,
    }


@app.delete("/api/openapi/spec")
async def openapi_delete():
    reader = get_reader()
    for f in reader.openapi_dir.glob("*"):
        f.unlink()
    return {"ok": True}


@app.post("/api/openapi/merge-shadow")
async def openapi_merge_shadow(payload: dict = Body(default=None)):
    """업로드된 OpenAPI 스펙에 선택된 shadow endpoint 들을 병합.

    Body: {"endpoints": [{"method": "GET", "endpoint": "/foo"}]}
    """
    reader = get_reader()
    spec_path = reader.get_openapi_spec_path()
    if not spec_path:
        raise HTTPException(status_code=400, detail="No OpenAPI spec has been uploaded.")

    requested = []
    if payload and isinstance(payload.get("endpoints"), list):
        for it in payload["endpoints"]:
            m = (it.get("method") or "").upper().strip()
            ep = (it.get("endpoint") or "").strip()
            if m and ep:
                requested.append((m, ep))
    if not requested:
        raise HTTPException(status_code=400, detail="Select at least one endpoint to add.")

    result = reader.get_shadow_result()
    spec_shadow_map = {
        (s.method.upper(), s.endpoint): asdict(s)
        for s in result.shadow_endpoints if "spec" in s.source
    }

    selected, skipped = [], []
    for key in requested:
        if key in spec_shadow_map:
            selected.append(spec_shadow_map[key])
        else:
            skipped.append({"method": key[0], "endpoint": key[1]})

    if not selected:
        raise HTTPException(
            status_code=400,
            detail="None of the selected endpoints are shadow endpoints (absent from the spec).",
        )

    suffix = spec_path.suffix.lower()
    is_yaml = suffix in (".yaml", ".yml")
    with open(spec_path, "r", encoding="utf-8") as f:
        spec_data = yaml.safe_load(f) if is_yaml else json.load(f)

    added = merge_shadow_endpoints(spec_data, selected)

    with open(spec_path, "w", encoding="utf-8") as f:
        if is_yaml:
            yaml.safe_dump(spec_data, f, sort_keys=False, allow_unicode=True)
        else:
            json.dump(spec_data, f, indent=2, ensure_ascii=False)

    try:
        spec = parse_spec(str(spec_path))
        endpoint_count = spec.endpoint_count
    except Exception:
        endpoint_count = None

    logger.info(f"Merged {added} shadow APIs into the OpenAPI spec (requested {len(requested)}, skipped {len(skipped)})")
    return {
        "ok": True,
        "added": added,
        "requested": len(requested),
        "skipped": skipped,
        "endpoint_count": endpoint_count,
        "file_name": spec_path.name,
    }


@app.get("/api/openapi/export-all")
async def openapi_export_all():
    """기록된 모든 endpoint 를 단일 OpenAPI 3.0 스펙(JSON) 으로 다운로드."""
    inventory = get_reader().get_inventory()
    if not inventory:
        raise HTTPException(status_code=404, detail="The inventory is empty. Run the pipeline first.")

    spec_dict = build_full_spec(inventory)
    body = json.dumps(spec_dict, indent=2, ensure_ascii=False)
    fname = f"api-discovery-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ── Test Request (Try it out) ───────────────────────────

# 응답 본문 최대 200KB까지만 클라이언트로 전달
_MAX_RESPONSE_BYTES = 200_000
# 기본 타임아웃 10초, 최대 30초
_DEFAULT_TIMEOUT_S = 10.0
_MAX_TIMEOUT_S = 30.0
_ALLOWED_TEST_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


def _path_matches_template(template: str, path: str) -> bool:
    """Inventory의 /foo/{id} 템플릿이 실제 요청 path와 대응되는지 확인."""
    template = template or "/"
    path = path or "/"
    if not template.startswith("/"):
        template = "/" + template
    if not path.startswith("/"):
        path = "/" + path

    parts = []
    pos = 0
    for match in re.finditer(r"\{[^}/]+\}", template):
        parts.append(re.escape(template[pos:match.start()]))
        parts.append(r"[^/?#]+")
        pos = match.end()
    parts.append(re.escape(template[pos:]))
    return re.fullmatch("".join(parts), path) is not None


def _find_test_target(
    inventory: list,
    method: str,
    domain: str,
    endpoint_template: str,
    path: str,
) -> Optional[dict]:
    """요청 대상이 발견된 inventory 항목인지 검증하고 해당 항목을 반환."""
    for entry in inventory:
        entry_method = (entry.get("method") or "").upper()
        if entry_method != method:
            continue
        if domain not in (entry.get("domains") or []):
            continue
        entry_endpoint = entry.get("endpoint") or "/"
        if endpoint_template and entry_endpoint != endpoint_template:
            continue
        if _path_matches_template(entry_endpoint, path):
            return entry
    return None


def _normalize_header_map(headers: dict) -> dict:
    clean = {}
    for key, value in headers.items():
        k = str(key).strip()
        if not k or "\r" in k or "\n" in k:
            continue
        clean[k] = str(value)
    return clean


@app.post("/api/test/request")
async def test_request(payload: dict = Body(...)):
    """Discovery된 endpoint로 실제 요청을 보내고 응답을 반환.

    SSRF 방어: 요청 대상 domain은 inventory에서 발견된 domain 으로 제한.
    """
    method = (payload.get("method") or "GET").upper()
    domain = (payload.get("domain") or "").strip()
    scheme = (payload.get("scheme") or "https").strip().lower()
    endpoint_template = (payload.get("endpoint") or "").strip()
    path = payload.get("path") or "/"
    query = payload.get("query") if isinstance(payload.get("query"), dict) else {}
    headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}
    headers = _normalize_header_map(headers)
    body = payload.get("body")

    if method not in _ALLOWED_TEST_METHODS:
        raise HTTPException(status_code=400, detail=f"Method '{method}' is not allowed.")
    if scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Scheme must be either http or https.")
    if not domain:
        raise HTTPException(status_code=400, detail="A domain is required.")

    # 포트: 미지정/기본(80·443)이면 표기 생략, 그 외에는 domain:port 로.
    netloc = domain
    raw_port = payload.get("port")
    if raw_port not in (None, "", 0):
        try:
            port = int(raw_port)
            if not (1 <= port <= 65535):
                raise ValueError
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Port must be a number between 1 and 65535.")
        if port != (443 if scheme == "https" else 80):
            netloc = f"{domain}:{port}"

    if not path.startswith("/"):
        path = "/" + path

    inventory = get_reader().get_inventory()
    target = _find_test_target(inventory, method, domain, endpoint_template, path)
    if not target:
        raise HTTPException(
            status_code=400,
            detail="The target must be a domain/endpoint pair present in the discovered inventory.",
        )

    try:
        timeout_s = float(payload.get("timeout_ms", _DEFAULT_TIMEOUT_S * 1000)) / 1000
    except (TypeError, ValueError):
        timeout_s = _DEFAULT_TIMEOUT_S
    timeout_s = min(max(timeout_s, 1.0), _MAX_TIMEOUT_S)

    content = None
    if body not in (None, "") and method in ("POST", "PUT", "PATCH", "DELETE"):
        if isinstance(body, (dict, list)):
            content = json.dumps(body, ensure_ascii=False).encode("utf-8")
            if not any(k.lower() == "content-type" for k in headers):
                headers["Content-Type"] = "application/json"
        else:
            content = str(body).encode("utf-8")

    url = f"{scheme}://{netloc}{path}"
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(
            timeout=timeout_s,
            follow_redirects=False,
        ) as client:
            resp = await client.request(
                method,
                url,
                params=query or None,
                headers=headers,
                content=content,
            )
        elapsed_ms = (time.monotonic() - start) * 1000

        body_bytes = resp.content
        truncated = False
        if len(body_bytes) > _MAX_RESPONSE_BYTES:
            body_bytes = body_bytes[:_MAX_RESPONSE_BYTES]
            truncated = True
        try:
            body_text = body_bytes.decode(resp.encoding or "utf-8", errors="replace")
        except (LookupError, UnicodeDecodeError):
            body_text = body_bytes.decode("utf-8", errors="replace")

        return {
            "ok": True,
            "status_code": resp.status_code,
            "reason_phrase": resp.reason_phrase,
            "elapsed_ms": round(elapsed_ms, 1),
            "request_url": str(resp.request.url),
            "response_headers": dict(resp.headers),
            "response_body": body_text,
            "body_truncated": truncated,
            "content_length": len(resp.content),
        }
    except httpx.TimeoutException:
        return {"ok": False, "error": f"timeout (exceeded {timeout_s:.1f}s)"}
    except httpx.RequestError as e:
        return {"ok": False, "error": f"Request failed: {e}"}


# ── Ingest (에이전트 수신) ──────────────────────────────


def _get_ingest_token() -> str:
    # 환경변수 우선 — 이미지에 비밀값을 굽지 않고 배포할 수 있게 한다.
    env_token = os.environ.get("INGEST_TOKEN")
    if env_token is not None:
        return env_token
    try:
        cfg = yaml.safe_load(open(_config_path))
        return cfg.get("ingest", {}).get("token", "")
    except Exception:
        return ""


@app.post("/api/ingest")
async def ingest_logs(request: Request, payload: dict = Body(...)):
    """에이전트로부터 파싱된 로그 배치를 수신해 DB에 저장.

    Authorization: Bearer <token> 헤더로 인증.
    settings.yaml의 ingest.token이 비어있으면 인증 건너뜀 (로컬 모드).
    """
    expected = _get_ingest_token()
    if expected:
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ").strip()
        if token != expected:
            raise HTTPException(status_code=401, detail="Invalid token")

    rows_data = payload.get("rows", [])

    # 데이터가 없어도 에이전트 heartbeat는 기록
    if not rows_data:
        agent_id = payload.get("agent_id") or request.client.host
        poll_interval = int(payload.get("poll_interval", 30))
        nginx_status = payload.get("nginx_status", "unknown")
        nginx_plus = payload.get("nginx_plus") or {}
        nginx_edition = payload.get("nginx_edition", "unknown")
        _record_agent(agent_id, request.client.host, poll_interval, 0, nginx_status, nginx_plus, nginx_edition)
        return {"ok": True, "inserted": 0}

    cfg = yaml.safe_load(open(_config_path))
    from src.discovery.normalizer import URINormalizer
    normalizer = URINormalizer(
        rules=cfg["discovery"]["normalizers"],
        exclude_prefixes=cfg["discovery"].get("exclude_prefixes", []),
        exclude_extensions=cfg["discovery"].get("exclude_extensions", []),
    )

    now = datetime.now(KST).isoformat(timespec="seconds")
    rows = []
    for r in rows_data:
        uri = r.get("uri", "")
        rows.append((
            r.get("time", ""), r.get("remote_addr", ""), r.get("method", ""),
            uri, normalizer.normalize(uri), normalizer.extract_version(uri),
            r.get("query_string", ""), int(r.get("status", 0)),
            int(r.get("body_bytes_sent", 0)), int(r.get("request_length", 0)),
            float(r.get("request_time", 0.0)), r.get("upstream_response_time"),
            r.get("http_user_agent", ""), r.get("http_authorization", "-"),
            int(r.get("has_auth", 0)), r.get("auth_type", ""),
            r.get("host", ""), r.get("request_id", ""),
            now,
        ))

    from src.db.log_store import LogStore
    store = LogStore(
        db_path=cfg["pipeline"].get("db_path", "./output/api_logs.db"),
        retain_days=cfg["pipeline"].get("retain_days", 7),
    )
    inserted = store.insert_batch(rows)

    agent_id = payload.get("agent_id") or request.client.host
    poll_interval = int(payload.get("poll_interval", 30))
    nginx_status = payload.get("nginx_status", "unknown")
    nginx_plus = payload.get("nginx_plus") or {}
    nginx_edition = payload.get("nginx_edition", "unknown")
    _record_agent(agent_id, request.client.host, poll_interval, inserted, nginx_status, nginx_plus, nginx_edition)

    logger.info(f"[ingest] {agent_id} -> stored {inserted} records")
    return {"ok": True, "inserted": inserted}


@app.get("/api/agents")
async def api_agents():
    """등록된 에이전트 목록과 Online/Offline/Unknown 상태 반환."""
    with _agents_lock:
        result = [
            {
                **a,
                "status": _agent_status(a["last_seen_ts"], a["poll_interval"]),
            }
            for a in _agents.values()
        ]
    return sorted(result, key=lambda x: x["last_seen_ts"], reverse=True)


# ── Logs ────────────────────────────────────────────────

@app.get("/api/logs")
async def logs(
    page: int = 1,
    per_page: int = 100,
    method: str = "",
    uri: str = "",
    sort: str = "time",
    order: str = "desc",
    date_from: str = "",
    date_to: str = "",
):
    from src.db.log_store import LogStore
    cfg = yaml.safe_load(open(_config_path))
    store = LogStore(
        db_path=cfg["pipeline"].get("db_path", "./output/api_logs.db"),
        retain_days=cfg["pipeline"].get("retain_days", 7),
    )
    rows, total = store.fetch_page(
        page=max(1, page),
        per_page=min(per_page, 500),
        method=method,
        uri=uri,
        sort=sort,
        order=order,
        date_from=date_from,
        date_to=date_to,
    )
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "rows": rows,
    }


# ── Pipeline ────────────────────────────────────────────

@app.post("/api/pipeline/run")
async def pipeline_run(background_tasks: BackgroundTasks):
    if _pipeline["running"]:
        return {"ok": False, "message": "A run is already in progress."}
    # 수동 Run Now는 데이터(Inventory)만 빠르게 갱신. 모델 재학습은 daily 스케줄에서.
    background_tasks.add_task(_run_pipeline_task, "manual", True)
    return {"ok": True, "message": "Data refresh started"}


@app.get("/api/pipeline/status")
async def pipeline_status():
    return _pipeline

#!/usr/bin/env python3
"""
NGINX API Discovery — Log Collection Agent

NGINX Plus VM에서 실행되는 경량 에이전트.
로그를 파싱해 Dashboard VM의 /api/ingest 엔드포인트로 전송한다.

의존성: pyyaml (pip install pyyaml)
"""

import gzip
import json
import logging
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request as HttpRequest, urlopen

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── NGINX Plus REST API 수집 ─────────────────────────────────


def _fetch_nginx_plus(api_url: str) -> dict:
    """NGINX Plus REST API에서 주요 메트릭을 수집."""
    paths = {
        "nginx":         "/nginx",
        "connections":   "/connections",
        "http_requests": "/http/requests",
        "ssl":           "/ssl",
        "processes":     "/processes",
        "license":       "/license",
    }
    result = {}
    base = api_url.rstrip("/")
    for key, path in paths.items():
        try:
            req = HttpRequest(base + path, headers={"Accept": "application/json"})
            with urlopen(req, timeout=3) as r:
                result[key] = json.loads(r.read().decode())
        except Exception:
            pass
    return result


def _check_stub_status(url: str) -> bool:
    """NGINX OSS stub_status 엔드포인트가 응답하면 True (nginx 살아있음)."""
    try:
        req = HttpRequest(url, headers={"Accept": "text/plain"})
        with urlopen(req, timeout=3) as r:
            body = r.read().decode(errors="ignore")
        return r.status == 200 and "Active connections" in body
    except Exception:
        return False


# ── NGINX 상태 확인 ───────────────────────────────────────────


def _check_nginx() -> str:
    """NGINX 프로세스 상태 확인. systemctl → pgrep 순으로 시도."""
    for svc in ("nginx", "nginx-plus"):
        try:
            r = subprocess.run(
                ["systemctl", "is-active", svc],
                capture_output=True, text=True, timeout=5,
            )
            s = r.stdout.strip()
            if s in ("active", "inactive", "failed", "activating", "deactivating"):
                return s
        except Exception:
            pass
    try:
        r = subprocess.run(["pgrep", "-x", "nginx"], capture_output=True, timeout=3)
        return "active" if r.returncode == 0 else "inactive"
    except Exception:
        return "unknown"


# ── 로그 파싱 ─────────────────────────────────────────────────


def _parse_line(raw: str):
    """NGINX JSON 로그 1줄을 파싱. 실패 시 None."""
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        return None

    auth = d.get("http_authorization", "-") or "-"
    has_auth = auth not in ("-", "", "None")
    auth_type = ""
    if has_auth:
        auth_type = auth.split()[0] if " " in auth else "token"

    upstream_raw = d.get("upstream_response_time", "-")
    try:
        upstream = float(upstream_raw) if upstream_raw not in ("-", "", "None") else None
    except (ValueError, TypeError):
        upstream = None

    try:
        return {
            "time":                  d.get("time", ""),
            "remote_addr":           d.get("remote_addr", ""),
            "method":                d.get("method", "").upper(),
            "uri":                   d.get("uri", ""),
            "query_string":          d.get("query_string", ""),
            "status":                int(d.get("status", 0)),
            "body_bytes_sent":       int(d.get("body_bytes_sent", 0)),
            "request_length":        int(d.get("request_length", 0)),
            "request_time":          float(d.get("request_time", 0.0)),
            "upstream_response_time": upstream,
            "http_user_agent":       d.get("http_user_agent", ""),
            "http_authorization":    auth,
            "has_auth":              int(has_auth),
            "auth_type":             auth_type,
            "host":                  d.get("host", ""),
            "request_id":            d.get("request_id", ""),
        }
    except (ValueError, TypeError):
        return None


# ── URI 필터 ──────────────────────────────────────────────────


def _is_excluded(uri: str, prefixes: list, extensions: list) -> bool:
    for p in prefixes:
        if uri.startswith(p):
            return True
    dot = uri.split("?")[0].rfind(".")
    if dot != -1:
        ext = uri.split("?")[0][dot:].lower()
        return ext in extensions
    return False


# ── 커서 관리 (JSON 파일) ──────────────────────────────────────


class CursorStore:
    """읽기 위치(offset + inode)를 JSON 파일로 유지."""

    def __init__(self, path: str):
        self.path = Path(path)

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, data: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get(self, key: str) -> tuple:
        entry = self._load().get(key, {})
        return entry.get("offset", 0), entry.get("inode", 0)

    def set(self, key: str, offset: int, inode: int):
        d = self._load()
        d[key] = {"offset": offset, "inode": inode}
        self._save(d)


# ── HTTP 전송 ─────────────────────────────────────────────────


def _send_batch(url: str, token: str, rows: list, timeout: int = 30, **meta) -> bool:
    body = {"rows": rows}
    body.update(meta)
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = HttpRequest(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
            logger.info(f"Sent: {body.get('inserted', '?')} records ingested")
            return True
    except HTTPError as e:
        logger.error(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
    except URLError as e:
        logger.error(f"Connection error: {e.reason}")
    except Exception as e:
        logger.error(f"Send failed: {e}")
    return False


# ── 에이전트 ──────────────────────────────────────────────────


class Agent:
    def __init__(self, config_path: str):
        # 설정 파일은 선택 사항 — 없으면 환경변수만으로 동작한다 (컨테이너 배포용).
        cfg = {}
        if config_path and os.path.exists(config_path):
            with open(config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

        # 환경변수 > 설정 파일 > 기본값 순으로 값을 결정한다.
        def _get(env_key, cfg_key, default=None):
            v = os.environ.get(env_key)
            return v if v is not None else cfg.get(cfg_key, default)

        dashboard_url = _get("DASHBOARD_URL", "dashboard_url")
        token = _get("INGEST_TOKEN", "ingest_token")
        log_path = _get("LOG_PATH", "log_path")
        if not dashboard_url:
            raise ValueError("dashboard_url is not set - provide DASHBOARD_URL or set it in the config file")
        if not log_path:
            raise ValueError("log_path is not set - provide LOG_PATH or set it in the config file")

        self.ingest_url = dashboard_url.rstrip("/") + "/api/ingest"
        self.token = token or ""
        self.log_path = Path(log_path)
        rotate_dir = _get("LOG_ROTATE_DIR", "log_rotate_dir", "")
        self.rotate_dir = Path(rotate_dir) if rotate_dir else None
        self.rotate_pattern = _get("LOG_ROTATE_PATTERN", "log_rotate_pattern", "api_access.log-*.gz")
        self.cursor = CursorStore(_get("CURSOR_FILE", "cursor_file", "./agent_cursor.json"))
        self._agent_id = os.environ.get("AGENT_ID") or socket.gethostname()
        self.batch_size = int(_get("BATCH_SIZE", "batch_size", 5000))
        self.poll_interval = int(_get("POLL_INTERVAL", "poll_interval", 30))
        self.nginx_plus_api = (_get("NGINX_PLUS_API", "nginx_plus_api", "") or "").strip().rstrip("/")
        # NGINX 종류 식별: plus / oss / auto(기본).
        # auto = Plus API 응답이 있으면 plus, 없으면 oss 로 판정.
        self.nginx_edition = (_get("NGINX_EDITION", "nginx_edition", "auto") or "auto").strip().lower()
        # NGINX OSS stub_status 엔드포인트 (예: http://127.0.0.1:8080/nginx_status).
        # 컨테이너에서 OSS 상태(active)를 확인하는 용도. 비우면 로그 신선도로 대체.
        self.nginx_status_url = (_get("NGINX_STATUS_URL", "nginx_status_url", "") or "").strip().rstrip("/")
        self.retain_days = int(_get("RETAIN_DAYS", "retain_days", 7))
        skip_env = os.environ.get("SKIP_ERROR_RESPONSES")
        if skip_env is not None:
            self.skip_errors = skip_env.strip().lower() in ("1", "true", "yes", "on")
        else:
            self.skip_errors = bool(cfg.get("skip_error_responses", True))
        self.exclude_prefixes = cfg.get("exclude_prefixes", [])
        self.exclude_extensions = cfg.get("exclude_extensions", [])

    # ── 수집 ────────────────────────────────────────────────

    def _collect_rotated(self):
        if not self.rotate_dir or not self.rotate_dir.exists():
            return []

        cutoff = datetime.now() - timedelta(days=self.retain_days)
        plain_pattern = self.rotate_pattern[:-3] if self.rotate_pattern.endswith(".gz") else None

        candidates = [(p, True) for p in self.rotate_dir.glob(self.rotate_pattern)]
        if plain_pattern:
            candidates += [
                (p, False) for p in self.rotate_dir.glob(plain_pattern)
                if not p.name.endswith(".gz")
            ]

        rows = []
        for rot_file, compressed in sorted(candidates, key=lambda x: x[0].name):
            m = re.search(r"(\d{8})", rot_file.name)
            if not m:
                continue
            try:
                file_date = datetime.strptime(m.group(1), "%Y%m%d")
            except ValueError:
                continue
            if file_date < cutoff:
                continue

            key = str(rot_file)
            stored_offset, _ = self.cursor.get(key)
            if stored_offset == -1:  # 이미 완전 처리
                continue

            try:
                opener = (
                    gzip.open(rot_file, "rt", encoding="utf-8", errors="replace")
                    if compressed
                    else open(rot_file, "r", encoding="utf-8", errors="replace")
                )
                with opener as f:
                    for raw in f:
                        line = raw.strip()
                        if not line:
                            continue
                        parsed = _parse_line(line)
                        if not parsed:
                            continue
                        if self.skip_errors and parsed["status"] >= 400:
                            continue
                        if _is_excluded(parsed["uri"], self.exclude_prefixes, self.exclude_extensions):
                            continue
                        rows.append(parsed)

                self.cursor.set(key, -1, 0)
                logger.info(f"Rotated file processed: {rot_file.name}")
            except Exception as e:
                logger.warning(f"Failed to read rotated file {rot_file.name}: {e}")

        return rows

    def _collect_active(self):
        if not self.log_path.exists():
            logger.warning(f"Log file not found: {self.log_path}")
            return []

        key = str(self.log_path)
        stat = self.log_path.stat()
        current_inode, current_size = stat.st_ino, stat.st_size
        stored_offset, stored_inode = self.cursor.get(key)

        if stored_inode != 0 and current_inode != stored_inode:
            logger.info("Log file replaced (logrotate) - reading from the start")
            stored_offset = 0
        elif stored_offset > current_size:
            logger.info("Truncation detected - reading from the start")
            stored_offset = 0

        rows = []
        with open(key, "r", encoding="utf-8", errors="replace") as f:
            f.seek(stored_offset)
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                parsed = _parse_line(line)
                if not parsed:
                    continue
                if self.skip_errors and parsed["status"] >= 400:
                    continue
                if _is_excluded(parsed["uri"], self.exclude_prefixes, self.exclude_extensions):
                    continue
                rows.append(parsed)
            new_offset = f.tell()

        self.cursor.set(key, new_offset, current_inode)
        return rows

    # ── 전송 ────────────────────────────────────────────────

    def _flush(self, rows, nginx_status="unknown", nginx_plus=None, nginx_edition="unknown"):
        meta = dict(
            agent_id=self._agent_id,
            poll_interval=self.poll_interval,
            nginx_status=nginx_status,
            nginx_plus=nginx_plus or {},
            nginx_edition=nginx_edition,
        )
        if not rows:
            return _send_batch(self.ingest_url, self.token, [], **meta)
        for i in range(0, len(rows), self.batch_size):
            chunk = rows[i: i + self.batch_size]
            if not _send_batch(self.ingest_url, self.token, chunk, **meta):
                return False
        return True

    # ── 메인 루프 ────────────────────────────────────────────

    def _log_recently_written(self) -> bool:
        """활성 로그 파일이 최근에 기록됐으면 True (트래픽 기반 liveness 판정)."""
        try:
            mtime = self.log_path.stat().st_mtime
        except OSError:
            return False
        return (time.time() - mtime) < max(self.poll_interval * 3, 120)

    def run_once(self):
        nginx_status = _check_nginx()
        nginx_plus   = _fetch_nginx_plus(self.nginx_plus_api) if self.nginx_plus_api else {}
        # 컨테이너 등 systemctl/pgrep 을 쓸 수 없는 환경('unknown')에서는 아래 순서로 보정:
        #   1) Plus API 응답 여부   2) OSS stub_status 응답 여부
        #   3) 활성 로그가 최근에 기록됐는지 (트래픽 기반, 설정 불필요)
        # 어떤 신호도 없으면 '중지'와 '유휴'를 구분할 수 없으므로 unknown 으로 남긴다.
        if nginx_status == "unknown":
            if self.nginx_plus_api:
                nginx_status = "active" if nginx_plus else "failed"
            elif self.nginx_status_url:
                nginx_status = "active" if _check_stub_status(self.nginx_status_url) else "failed"
            elif self._log_recently_written():
                nginx_status = "active"
        # NGINX 종류 판정 (auto면 Plus API 응답 유무로 결정)
        edition = self.nginx_edition
        if edition not in ("plus", "oss"):
            edition = "plus" if nginx_plus else "oss"
        rotated = self._collect_rotated()
        active  = self._collect_active()
        total   = len(rotated) + len(active)
        if total:
            logger.info(f"Collected: {len(rotated)} rotated + {len(active)} active | nginx={nginx_status}")
        if nginx_plus:
            ver = nginx_plus.get("nginx", {}).get("version", "")
            logger.info(f"NGINX Plus metrics collected (v{ver})")
        self._flush(rotated + active, nginx_status=nginx_status, nginx_plus=nginx_plus, nginx_edition=edition)

    def run(self):
        logger.info(
            f"Agent started - dashboard={self.ingest_url}, poll={self.poll_interval}s"
        )
        while True:
            try:
                self.run_once()
            except Exception as e:
                logger.exception(f"Run failed: {e}")
            time.sleep(self.poll_interval)


# ── 진입점 ───────────────────────────────────────────────────


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="NGINX API Discovery Agent")
    p.add_argument(
        "--config",
        default="agent_config.yaml",
        help="Path to the agent config file (default: agent_config.yaml)",
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (for use with cron or another external scheduler)",
    )
    args = p.parse_args()

    agent = Agent(args.config)
    if args.once:
        agent.run_once()
    else:
        agent.run()

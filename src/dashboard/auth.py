"""대시보드 세션 인증 (stdlib 전용, 외부 의존성 없음).

- 비밀번호: pbkdf2_hmac(sha256) 해시. 평문은 어디에도 저장하지 않는다.
- 세션: HMAC-SHA256 서명 쿠키. 서버는 상태를 저장하지 않는다(stateless).
- 역할: admin / viewer 2단계. config/settings.yaml의 auth.users로 정의.
  users가 비어 있으면 인증 비활성화(로컬 모드) — ingest.token 정책과 동일.

CLI:
    python3 -m src.dashboard.auth hash        # 비밀번호 해시 생성(입력 숨김)
    python3 -m src.dashboard.auth secret      # 랜덤 세션 서명키 생성
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

COOKIE_NAME = "nad_session"
_PBKDF2_ITER = 240_000
_ALGO = "pbkdf2_sha256"

# 초기 배포 시 자동 생성되는 기본 관리자 계정
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASSWORD = "admin1234"
_STORE_FILE = "auth_users.json"   # output/ (쓰기 가능 볼륨)에 저장
_SECRET_FILE = "auth_secret"

# 설정에 secret이 없을 때 프로세스 수명 동안만 쓰는 임시 서명키.
# (재시작하면 세션 무효화됨 — 운영에선 DASHBOARD_SECRET/auth.secret 지정 권장)
_EPHEMERAL_SECRET = secrets.token_hex(32)


# ── 비밀번호 해시 ────────────────────────────────────────

def hash_password(password: str, iterations: int = _PBKDF2_ITER) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"{_ALGO}${iterations}${_b64e(salt)}${_b64e(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iter_s, salt_b64, hash_b64 = stored.split("$")
        if algo != _ALGO:
            return False
        salt = _b64d(salt_b64)
        expected = _b64d(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iter_s))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# ── 서명 세션 쿠키 ───────────────────────────────────────

def make_session(username: str, role: str, secret: str, ttl_seconds: int) -> str:
    payload = {"u": username, "r": role, "exp": int(time.time()) + int(ttl_seconds)}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    sig = _sign(body, secret)
    return f"{body}.{sig}"


def verify_session(cookie: str, secret: str):
    """유효하면 {'username','role'} 반환, 아니면 None."""
    if not cookie or "." not in cookie:
        return None
    body, _, sig = cookie.partition(".")
    if not hmac.compare_digest(sig, _sign(body, secret)):
        return None
    try:
        payload = json.loads(_b64d(body))
    except Exception:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return {"username": payload.get("u"), "role": payload.get("r")}


# ── 설정 로딩 ────────────────────────────────────────────

def _config_users(config_path: str) -> tuple:
    """settings.yaml의 정적 auth 설정을 (users, secret, session_hours)로 반환."""
    try:
        cfg = yaml.safe_load(open(config_path)) or {}
    except Exception:
        cfg = {}
    auth_cfg = cfg.get("auth") or {}
    users = {}
    for u in auth_cfg.get("users") or []:
        name = u.get("username")
        ph = u.get("password_hash")
        if not name or not ph:
            continue
        role = "admin" if u.get("role") == "admin" else "viewer"
        users[name] = {"role": role, "password_hash": ph}
    return users, auth_cfg.get("secret") or "", auth_cfg.get("session_hours", 12)


# ── 관리형 계정 저장소 (output/auth_users.json, 쓰기 가능) ──

def _store_path(output_dir: str) -> Path:
    return Path(output_dir) / _STORE_FILE


def load_managed_users(output_dir: str) -> dict:
    """{username: {role, password_hash}}"""
    p = _store_path(output_dir)
    if not p.exists():
        return {}
    try:
        data = json.load(open(p))
    except Exception:
        logger.warning("Failed to read auth_users.json - falling back to an empty store")
        return {}
    users = {}
    for u in data.get("users") or []:
        name = u.get("username")
        ph = u.get("password_hash")
        if not name or not ph:
            continue
        role = "admin" if u.get("role") == "admin" else "viewer"
        users[name] = {"role": role, "password_hash": ph}
    return users


def _save_managed_users(output_dir: str, users: dict):
    p = _store_path(output_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {"users": [
        {"username": n, "role": u["role"], "password_hash": u["password_hash"]}
        for n, u in users.items()
    ]}
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(p)   # 원자적 교체


def list_users(output_dir: str) -> list:
    return [{"username": n, "role": u["role"]}
            for n, u in sorted(load_managed_users(output_dir).items())]


def add_user(output_dir: str, username: str, role: str, password: str):
    users = load_managed_users(output_dir)
    users[username] = {
        "role": "admin" if role == "admin" else "viewer",
        "password_hash": hash_password(password),
    }
    _save_managed_users(output_dir, users)


def delete_user(output_dir: str, username: str):
    users = load_managed_users(output_dir)
    if username in users:
        del users[username]
        _save_managed_users(output_dir, users)


def set_password(output_dir: str, username: str, password: str) -> bool:
    users = load_managed_users(output_dir)
    if username not in users:
        return False
    users[username]["password_hash"] = hash_password(password)
    _save_managed_users(output_dir, users)
    return True


# ── 서명키: env → config → output/auth_secret(자동 생성·보존) ──

def resolve_secret(config_secret: str, output_dir: str) -> str:
    env = os.environ.get("DASHBOARD_SECRET")
    if env:
        return env
    if config_secret:
        return config_secret
    p = Path(output_dir) / _SECRET_FILE
    if p.exists():
        try:
            s = p.read_text().strip()
            if s:
                return s
        except Exception:
            pass
    s = secrets.token_hex(32)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(s)
        return s
    except Exception:
        logger.warning("Failed to persist auth_secret - using an ephemeral signing key (sessions drop on restart)")
        return _EPHEMERAL_SECRET


# ── 통합 로딩 ────────────────────────────────────────────

def load_auth_config(config_path: str, output_dir: str) -> dict:
    """config 정적 계정 + output 관리형 계정을 합쳐 정규화해 반환.

    계정이 하나도 없으면 기본 admin(admin/admin1234)을 output 저장소에 시딩한다.
    반환: {enabled, secret, session_seconds, users:{name:{role,password_hash}}, output_dir}
    """
    cfg_users, cfg_secret, session_hours = _config_users(config_path)
    managed = load_managed_users(output_dir)

    # 최초 기동: 계정이 전혀 없으면 기본 관리자 시딩
    if not cfg_users and not managed:
        add_user(output_dir, DEFAULT_ADMIN_USER, "admin", DEFAULT_ADMIN_PASSWORD)
        managed = load_managed_users(output_dir)
        logger.warning(
            "기본 관리자 계정 생성: %s / %s — 로그인 후 반드시 비밀번호를 변경하세요.",
            DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD,
        )

    merged = {**cfg_users, **managed}   # 관리형이 config와 충돌 시 우선

    try:
        session_seconds = int(float(session_hours) * 3600)
    except (TypeError, ValueError):
        session_seconds = 12 * 3600

    return {
        "enabled": bool(merged),
        "secret": resolve_secret(cfg_secret, output_dir),
        "session_seconds": session_seconds,
        "users": merged,
        "output_dir": output_dir,
    }


# ── 내부 유틸 ────────────────────────────────────────────

def _sign(body: str, secret: str) -> str:
    return _b64e(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ── CLI ──────────────────────────────────────────────────

if __name__ == "__main__":
    import getpass
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "hash"
    if cmd == "secret":
        print(secrets.token_hex(32))
    elif cmd == "hash":
        pw = getpass.getpass("비밀번호: ")
        if pw != getpass.getpass("확인: "):
            print("mismatch", file=sys.stderr)
            sys.exit(1)
        print(hash_password(pw))
    else:
        print(f"Unknown command: {cmd} (hash|secret)", file=sys.stderr)
        sys.exit(1)

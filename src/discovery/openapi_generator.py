"""
OpenAPI 스펙 생성 / 병합 유틸리티.

build_full_spec        : inventory 전체로부터 OpenAPI 3.0 스펙 생성
merge_shadow_endpoints : 기존 스펙(2.0/3.0)에 shadow endpoint 들을 paths 로 추가
"""

import re
from datetime import datetime
from typing import Iterable, List, Tuple


_PARAM_TYPE = {"id": "integer", "uuid": "string", "date": "string", "hash": "string"}


def _split_path_params(path: str) -> Tuple[str, List[str]]:
    """경로의 {param} 자리를 유지하면서 중복 이름은 자동 번호 부여."""
    seen: dict = {}
    names: List[str] = []

    def replace(match):
        raw = match.group(1)
        cnt = seen.get(raw, 0)
        seen[raw] = cnt + 1
        name = raw if cnt == 0 else f"{raw}{cnt + 1}"
        names.append(name)
        return f"{{{name}}}"

    return re.sub(r"\{([^}]+)\}", replace, path), names


def _param_schema(name: str, is_v3: bool) -> dict:
    base = re.sub(r"\d+$", "", name)
    typ = _PARAM_TYPE.get(base, "string")
    param = {"name": name, "in": "path", "required": True, "description": f"{base} parameter"}
    if is_v3:
        param["schema"] = {"type": typ}
    else:
        param["type"] = typ
    return param


def _derive_tags(path: str) -> List[str]:
    segs = [s for s in path.split("/") if s and not s.startswith("{")]
    return [segs[0]] if segs else ["root"]


def _build_operation(
    method: str,
    path: str,
    has_auth: bool,
    is_v3: bool = True,
    description: str = "",
) -> dict:
    _, param_names = _split_path_params(path)
    op = {
        "summary": f"{method.upper()} {path}",
        "tags": _derive_tags(path),
        "responses": {"200": {"description": "Successful response"}},
    }
    if description:
        op["description"] = description
    if param_names:
        op["parameters"] = [_param_schema(n, is_v3) for n in param_names]
    if has_auth:
        op["security"] = [{"BearerAuth": []}]
    return op


def _ensure_security_scheme(spec_data: dict, is_v3: bool) -> None:
    if is_v3:
        comps = spec_data.setdefault("components", {})
        schemes = comps.setdefault("securitySchemes", {})
        schemes.setdefault("BearerAuth", {"type": "http", "scheme": "bearer"})
    else:
        sec = spec_data.setdefault("securityDefinitions", {})
        sec.setdefault("BearerAuth", {"type": "apiKey", "name": "Authorization", "in": "header"})


def build_full_spec(inventory: List[dict], title: str = "API Discovery Export") -> dict:
    """Inventory 전체를 OpenAPI 3.0 스펙으로 생성."""
    spec = {
        "openapi": "3.0.1",
        "info": {
            "title": title,
            "version": datetime.now().strftime("%Y.%m.%d"),
            "description": (
                f"NGINX API Discovery가 운영 트래픽으로부터 자동 생성한 스펙. "
                f"총 {len(inventory)}개 endpoint, "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 시점."
            ),
        },
        "components": {
            "securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer"},
            }
        },
        "paths": {},
    }

    domains = sorted({d for e in inventory for d in (e.get("domains") or [])})
    if domains:
        spec["servers"] = [{"url": f"https://{d}"} for d in domains]

    auth_used = False
    paths = spec["paths"]
    for entry in inventory:
        path = entry.get("endpoint") or "/"
        method = (entry.get("method") or "GET").lower()
        norm_path, _ = _split_path_params(path)
        path_item = paths.setdefault(norm_path, {})
        if method in path_item:
            continue
        has_auth = bool(entry.get("has_auth"))
        if has_auth:
            auth_used = True
        desc_bits = []
        if entry.get("call_count"):
            desc_bits.append(f"call_count={entry['call_count']}")
        if entry.get("unique_ip_count"):
            desc_bits.append(f"unique_ips={entry['unique_ip_count']}")
        if entry.get("first_seen"):
            desc_bits.append(f"first_seen={entry['first_seen']}")
        if entry.get("last_seen"):
            desc_bits.append(f"last_seen={entry['last_seen']}")
        path_item[method] = _build_operation(
            method, path, has_auth, is_v3=True,
            description=" · ".join(desc_bits),
        )

    if not auth_used:
        spec["components"]["securitySchemes"].pop("BearerAuth", None)
        if not spec["components"]["securitySchemes"]:
            spec["components"].pop("securitySchemes")
        if not spec["components"]:
            spec.pop("components")

    return spec


def merge_shadow_endpoints(spec_data: dict, shadow_endpoints: Iterable[dict]) -> int:
    """기존 spec 에 shadow endpoint 들을 추가. 추가된 개수를 반환.

    이미 (path, method) 가 존재하면 건너뜀 (덮어쓰지 않음).
    """
    is_v3 = "openapi" in spec_data
    paths = spec_data.setdefault("paths", {})
    base_path = "" if is_v3 else (spec_data.get("basePath", "") or "").rstrip("/")

    added = 0
    auth_used = False
    for sh in shadow_endpoints:
        full_path = sh.get("endpoint") or "/"
        spec_path = (
            full_path[len(base_path):] or "/"
            if base_path and full_path.startswith(base_path)
            else full_path
        )
        norm_path, _ = _split_path_params(spec_path)
        method = (sh.get("method") or "GET").lower()

        path_item = paths.setdefault(norm_path, {})
        if method in path_item:
            continue
        has_auth = bool(sh.get("has_auth"))
        auth_used = auth_used or has_auth
        path_item[method] = _build_operation(
            method, spec_path, has_auth, is_v3=is_v3,
            description="x-discovered-by: nginx-api-discovery (shadow)",
        )
        added += 1

    if auth_used:
        _ensure_security_scheme(spec_data, is_v3)
    return added

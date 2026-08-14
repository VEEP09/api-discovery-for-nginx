"""
Shadow API 탐지.
두 가지 소스를 결합:
  1. ML 기반 — call_count=1 (단발성 미식별 호출)
  2. Spec 기반 — OpenAPI에 정의되지 않은 endpoint에 실제 트래픽 발생

또한 Spec에는 있지만 트래픽이 전혀 없는 endpoint(사용 안 되는 API)도 도출.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Set

from src.discovery.openapi_parser import OpenAPISpec


@dataclass
class ShadowEndpoint:
    method: str
    endpoint: str
    source: str          # "ml" | "spec" | "ml+spec"
    call_count: int = 0
    error_rate: float = 0.0
    has_auth: bool = False
    unique_ip_count: int = 0
    first_seen: str = ""
    last_seen: str = ""
    domains: List[str] = field(default_factory=list)


@dataclass
class UnusedEndpoint:
    method: str
    path: str
    operation_id: str = ""
    summary: str = ""
    tags: List[str] = field(default_factory=list)


@dataclass
class ShadowDetectionResult:
    shadow_endpoints: List[ShadowEndpoint] = field(default_factory=list)
    unused_endpoints: List[UnusedEndpoint] = field(default_factory=list)
    documented_count: int = 0
    spec_total: int = 0
    has_spec: bool = False


def _match_key(method: str, path: str) -> str:
    """path parameter 이름 무관하게 구조만 비교."""
    normalized = re.sub(r"\{[^}]+\}", "{}", path)
    return f"{method.upper()}:{normalized}"


def detect(
    inventory: List[dict],
    spec: Optional[OpenAPISpec] = None,
) -> ShadowDetectionResult:
    result = ShadowDetectionResult()

    # ── ML 기반: call_count = 1 ──────────────────────────
    ml_shadow_keys: Set[str] = set()
    for entry in inventory:
        if entry.get("call_count", 0) == 1:
            key = _match_key(entry["method"], entry["endpoint"])
            ml_shadow_keys.add(key)
            result.shadow_endpoints.append(ShadowEndpoint(
                method=entry["method"],
                endpoint=entry["endpoint"],
                source="ml",
                call_count=entry.get("call_count", 0),
                error_rate=entry.get("error_rate", 0.0),
                has_auth=entry.get("has_auth", False),
                unique_ip_count=entry.get("unique_ip_count", 0),
                first_seen=entry.get("first_seen", ""),
                last_seen=entry.get("last_seen", ""),
                domains=entry.get("domains", []),
            ))

    if spec is None:
        return result

    # ── Spec 기반 비교 ────────────────────────────────────
    result.has_spec = True
    result.spec_total = spec.endpoint_count

    spec_keys = spec.match_keys
    inv_key_map = {
        _match_key(e["method"], e["endpoint"]): e
        for e in inventory
    }

    # Spec에 없는데 트래픽이 있는 endpoint → Shadow
    for inv_key, entry in inv_key_map.items():
        if inv_key not in spec_keys:
            # 이미 ML shadow로 등록된 경우 source 업데이트
            existing = next(
                (s for s in result.shadow_endpoints
                 if _match_key(s.method, s.endpoint) == inv_key),
                None,
            )
            if existing:
                existing.source = "ml+spec"
            else:
                result.shadow_endpoints.append(ShadowEndpoint(
                    method=entry["method"],
                    endpoint=entry["endpoint"],
                    source="spec",
                    call_count=entry.get("call_count", 0),
                    error_rate=entry.get("error_rate", 0.0),
                    has_auth=entry.get("has_auth", False),
                    unique_ip_count=entry.get("unique_ip_count", 0),
                    first_seen=entry.get("first_seen", ""),
                    last_seen=entry.get("last_seen", ""),
                    domains=entry.get("domains", []),
                ))
        else:
            result.documented_count += 1

    # Spec에 있지만 트래픽이 없는 endpoint → Unused
    for oas_ep in spec.endpoints:
        if oas_ep.match_key not in inv_key_map:
            result.unused_endpoints.append(UnusedEndpoint(
                method=oas_ep.method,
                path=oas_ep.path,
                operation_id=oas_ep.operation_id,
                summary=oas_ep.summary,
                tags=oas_ep.tags,
            ))

    return result

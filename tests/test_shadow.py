import pytest
import yaml
from pathlib import Path

from src.discovery.openapi_parser import parse_spec, OpenAPISpec
from src.discovery.shadow_detector import detect, _match_key

SAMPLE_SPEC_V3 = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "paths": {
        "/api/v1/users/{userId}": {
            "get": {"operationId": "getUser", "summary": "Get user"},
            "delete": {"operationId": "deleteUser"},
        },
        "/api/v1/orders": {
            "get": {"operationId": "listOrders"},
            "post": {"operationId": "createOrder"},
        },
        "/api/v1/products": {
            "get": {"operationId": "listProducts"},
        },
    },
}

SAMPLE_SPEC_V2 = {
    "swagger": "2.0",
    "info": {"title": "Swagger API", "version": "2.0.0"},
    "basePath": "/api",
    "paths": {
        "/v1/users/{id}": {
            "get": {"operationId": "getUser"},
        },
    },
}

INVENTORY = [
    {"method": "GET",    "endpoint": "/api/v1/users/{id}",   "call_count": 100, "error_rate": 1.0, "has_auth": True,  "unique_ip_count": 10, "first_seen": "", "last_seen": ""},
    {"method": "DELETE", "endpoint": "/api/v1/users/{id}",   "call_count": 5,   "error_rate": 0.0, "has_auth": True,  "unique_ip_count": 2,  "first_seen": "", "last_seen": ""},
    {"method": "GET",    "endpoint": "/api/v1/orders",        "call_count": 50,  "error_rate": 2.0, "has_auth": False, "unique_ip_count": 5,  "first_seen": "", "last_seen": ""},
    # Spec에 없는 엔드포인트 (Shadow)
    {"method": "GET",    "endpoint": "/api/v1/admin/debug",   "call_count": 1,   "error_rate": 100, "has_auth": False, "unique_ip_count": 1,  "first_seen": "", "last_seen": ""},
    {"method": "POST",   "endpoint": "/api/v1/internal/hook", "call_count": 3,   "error_rate": 0.0, "has_auth": False, "unique_ip_count": 1,  "first_seen": "", "last_seen": ""},
]


@pytest.fixture
def spec_file(tmp_path):
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.dump(SAMPLE_SPEC_V3), encoding="utf-8")
    return str(path)


@pytest.fixture
def spec_v2_file(tmp_path):
    path = tmp_path / "swagger.yaml"
    path.write_text(yaml.dump(SAMPLE_SPEC_V2), encoding="utf-8")
    return str(path)


# ── Parser ────────────────────────────────────────────

def test_parse_v3(spec_file):
    spec = parse_spec(spec_file)
    assert spec.openapi_version.startswith("3")
    assert spec.title == "Test API"
    assert spec.endpoint_count == 5  # GET/DELETE users, GET/POST orders, GET products


def test_parse_v2(spec_v2_file):
    spec = parse_spec(spec_v2_file)
    assert spec.openapi_version.startswith("2")
    assert spec.base_path == "/api"
    assert spec.endpoint_count == 1


def test_parse_v3_match_keys(spec_file):
    spec = parse_spec(spec_file)
    # {userId}와 {id}는 같은 match_key여야 함
    assert "GET:/api/v1/users/{}" in spec.match_keys


def test_match_key_param_agnostic():
    assert _match_key("GET", "/users/{userId}") == _match_key("GET", "/users/{id}")
    assert _match_key("POST", "/orders/{orderId}/items") == _match_key("POST", "/orders/{id}/items")


# ── Detector ─────────────────────────────────────────

def test_detect_no_spec():
    result = detect(INVENTORY, spec=None)
    assert result.has_spec is False
    # ML 기반 shadow (call_count=1)
    assert any(s.source == "ml" for s in result.shadow_endpoints)
    ml_shadows = [s for s in result.shadow_endpoints if s.source == "ml"]
    assert len(ml_shadows) == 1  # admin/debug


def test_detect_with_spec(spec_file):
    spec = parse_spec(spec_file)
    result = detect(INVENTORY, spec=spec)
    assert result.has_spec is True
    assert result.spec_total == 5

    shadow_eps = {(s.method, s.endpoint) for s in result.shadow_endpoints}
    # admin/debug, internal/hook은 spec에 없으므로 shadow
    assert ("GET", "/api/v1/admin/debug") in shadow_eps
    assert ("POST", "/api/v1/internal/hook") in shadow_eps

    # GET /api/v1/users/{id}는 spec에 있으므로 shadow 아님
    assert ("GET", "/api/v1/users/{id}") not in shadow_eps


def test_detect_unused(spec_file):
    spec = parse_spec(spec_file)
    result = detect(INVENTORY, spec=spec)
    # POST /api/v1/orders는 spec에 있지만 inventory에 없음 → unused
    unused_paths = {(u.method, u.path) for u in result.unused_endpoints}
    assert ("POST", "/api/v1/orders") in unused_paths
    # GET /api/v1/products도 트래픽 없음 → unused
    assert ("GET", "/api/v1/products") in unused_paths


def test_detect_ml_plus_spec(spec_file):
    spec = parse_spec(spec_file)
    result = detect(INVENTORY, spec=spec)
    # admin/debug는 call_count=1(ML)이면서 spec에도 없음(spec) → ml+spec
    admin = next((s for s in result.shadow_endpoints if "admin" in s.endpoint), None)
    assert admin is not None
    assert admin.source == "ml+spec"

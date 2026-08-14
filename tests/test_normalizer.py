import pytest
from src.discovery.normalizer import URINormalizer

RULES = [
    {"name": "uuid", "pattern": r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "placeholder": "{uuid}"},
    {"name": "date", "pattern": r"\d{4}-\d{2}-\d{2}", "placeholder": "{date}"},
    {"name": "numeric_id", "pattern": r"\d+", "placeholder": "{id}"},
    {"name": "hex_hash", "pattern": r"[0-9a-f]{24,}", "placeholder": "{hash}"},
]
EXCLUDES = ["/static", "/health"]

@pytest.fixture
def normalizer():
    return URINormalizer(rules=RULES, exclude_prefixes=EXCLUDES)


@pytest.mark.parametrize("uri,expected", [
    ("/api/v1/users/1042", "/api/v1/users/{id}"),
    ("/api/v1/users/550e8400-e29b-41d4-a716-446655440000", "/api/v1/users/{uuid}"),
    ("/api/v1/reports/2024-03-01", "/api/v1/reports/{date}"),
    ("/api/v1/users/1042/orders/99", "/api/v1/users/{id}/orders/{id}"),
    ("/api/v1/status", "/api/v1/status"),
    ("/api/v1/users", "/api/v1/users"),
])
def test_normalize(normalizer, uri, expected):
    assert normalizer.normalize(uri) == expected


def test_exclude(normalizer):
    assert normalizer.normalize("/static/app.js") == "/static/app.js"
    assert normalizer.normalize("/health") == "/health"


def test_is_excluded(normalizer):
    assert normalizer.is_excluded("/static/img/logo.png") is True
    assert normalizer.is_excluded("/api/v1/users") is False


@pytest.mark.parametrize("uri,version", [
    ("/api/v1/users", "v1"),
    ("/api/v2/orders", "v2"),
    ("/users", ""),
])
def test_extract_version(normalizer, uri, version):
    assert normalizer.extract_version(uri) == version

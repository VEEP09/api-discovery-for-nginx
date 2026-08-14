import json
import pytest
from src.parser.log_parser import LogParser
from src.discovery.normalizer import URINormalizer
from src.features.extractor import FeatureExtractor
from src.features.vectorizer import FeatureVectorizer, NUMERIC_FEATURES
from src.features.sequence_builder import SequenceBuilder

RULES = [
    {"name": "uuid", "pattern": r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "placeholder": "{uuid}"},
    {"name": "date", "pattern": r"\d{4}-\d{2}-\d{2}", "placeholder": "{date}"},
    {"name": "numeric_id", "pattern": r"\d+", "placeholder": "{id}"},
]

SAMPLE_LOGS = [
    {
        "time": "2026-04-21T10:00:00+09:00", "remote_addr": "192.168.1.1",
        "method": "GET", "uri": "/api/v1/users/100", "query_string": "page=1",
        "status": 200, "body_bytes_sent": 512, "request_length": 200,
        "request_time": 0.05, "http_user_agent": "Mozilla/5.0",
        "http_referer": "-", "http_x_forwarded_for": "-",
        "http_authorization": "Bearer token123", "http_content_type": "-",
        "http_accept": "application/json", "upstream_response_time": "0.04",
        "server_name": "api.example.com", "request_id": "req001",
    },
    {
        "time": "2026-04-21T10:00:05+09:00", "remote_addr": "10.0.0.1",
        "method": "POST", "uri": "/api/v1/orders", "query_string": "",
        "status": 201, "body_bytes_sent": 128, "request_length": 512,
        "request_time": 0.12, "http_user_agent": "python-requests/2.28",
        "http_referer": "-", "http_x_forwarded_for": "-",
        "http_authorization": "-", "http_content_type": "application/json",
        "http_accept": "*/*", "upstream_response_time": "0.11",
        "server_name": "api.example.com", "request_id": "req002",
    },
    {
        "time": "2026-04-21T10:00:10+09:00", "remote_addr": "192.168.1.1",
        "method": "DELETE", "uri": "/api/v1/users/200", "query_string": "",
        "status": 404, "body_bytes_sent": 64, "request_length": 180,
        "request_time": 0.02, "http_user_agent": "Mozilla/5.0",
        "http_referer": "-", "http_x_forwarded_for": "-",
        "http_authorization": "Bearer token123", "http_content_type": "-",
        "http_accept": "application/json", "upstream_response_time": "-",
        "server_name": "api.example.com", "request_id": "req003",
    },
]


@pytest.fixture
def parsed_logs():
    parser = LogParser()
    return [parser.parse_line(json.dumps(log)) for log in SAMPLE_LOGS]


@pytest.fixture
def normalizer():
    return URINormalizer(rules=RULES)


@pytest.fixture
def raw_features(parsed_logs, normalizer):
    extractor = FeatureExtractor(normalizer=normalizer)
    return [extractor.extract(log) for log in parsed_logs]


def test_extractor_basic(raw_features):
    feat = raw_features[0]
    assert feat.method == "GET"
    assert feat.status == 200
    assert feat.has_auth == 1
    assert feat.auth_type == "Bearer"
    assert feat.is_error == 0
    assert feat.uri_depth == 4          # /api/v1/users/{id}
    assert feat.has_path_param == 1
    assert feat.is_internal_ip == 1     # 192.168.x
    assert feat.hour == 10


def test_extractor_bot_detection(raw_features):
    # python-requests는 봇으로 분류
    assert raw_features[1].is_bot == 1
    assert raw_features[1].is_browser == 0


def test_extractor_error(raw_features):
    assert raw_features[2].is_error == 1
    assert raw_features[2].status_class == 4


def test_vectorizer_output_dim(raw_features):
    vec = FeatureVectorizer()
    vectors = vec.fit_transform(raw_features)
    assert len(vectors) == len(raw_features)
    assert all(len(v) == len(NUMERIC_FEATURES) for v in vectors)


def test_vectorizer_scaled_range(raw_features):
    vec = FeatureVectorizer()
    vectors = vec.fit_transform(raw_features)
    for v in vectors:
        assert all(0.0 <= val <= 1.0 for val in v), f"스케일 범위 초과: {v}"


def test_vectorizer_save_load(raw_features, tmp_path):
    vec = FeatureVectorizer()
    original = vec.fit_transform(raw_features)
    path = str(tmp_path / "vec.json")
    vec.save(path)

    vec2 = FeatureVectorizer()
    vec2.load(path)
    reloaded = [vec2.transform(f) for f in raw_features]
    assert original == reloaded


def test_sequence_builder_sliding(raw_features):
    vec = FeatureVectorizer()
    vec.fit(raw_features)
    builder = SequenceBuilder(vectorizer=vec, window_size=2, step=1)
    # 192.168.1.1이 2개 요청 → 1개 시퀀스, 10.0.0.1이 1개 → 패딩 1개
    seqs = builder.build(raw_features)
    assert len(seqs) >= 1
    for seq in seqs:
        assert len(seq.vectors) == 2
        assert len(seq.timestamps) == 2


def test_sequence_padding(raw_features):
    vec = FeatureVectorizer()
    vec.fit(raw_features)
    builder = SequenceBuilder(vectorizer=vec, window_size=5, step=1)
    seqs = builder.build(raw_features)
    for seq in seqs:
        assert len(seq.vectors) == 5

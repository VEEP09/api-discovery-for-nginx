import json
import pytest
from src.parser.log_parser import LogParser, ParsedLog

SAMPLE_LOG = {
    "time": "2026-04-21T13:45:01+09:00",
    "remote_addr": "192.168.1.10",
    "method": "GET",
    "uri": "/api/v1/users/1042",
    "query_string": "include=profile",
    "status": 200,
    "body_bytes_sent": 512,
    "request_length": 320,
    "request_time": 0.043,
    "http_user_agent": "Mozilla/5.0",
    "http_referer": "-",
    "http_x_forwarded_for": "-",
    "http_authorization": "Bearer eyJtoken",
    "http_content_type": "-",
    "http_accept": "application/json",
    "upstream_response_time": "0.042",
    "server_name": "api.example.com",
    "request_id": "abc123",
}


@pytest.fixture
def parser():
    return LogParser()


def test_parse_valid_line(parser):
    raw = json.dumps(SAMPLE_LOG)
    result = parser.parse_line(raw)
    assert result is not None
    assert result.method == "GET"
    assert result.uri == "/api/v1/users/1042"
    assert result.status == 200
    assert result.has_auth is True
    assert result.auth_type == "Bearer"
    assert result.query_params == {"include": ["profile"]}


def test_parse_invalid_line(parser):
    result = parser.parse_line("not valid json {{")
    assert result is None
    assert parser.stats.failed == 1


def test_upstream_none_when_dash(parser):
    log = {**SAMPLE_LOG, "upstream_response_time": "-"}
    result = parser.parse_line(json.dumps(log))
    assert result.upstream_response_time is None


def test_stats_accumulate(parser):
    valid = json.dumps(SAMPLE_LOG)
    invalid = "bad"
    parser.parse_line(valid)
    parser.parse_line(invalid)
    assert parser.stats.total == 2
    assert parser.stats.success == 1
    assert parser.stats.failed == 1
    assert parser.stats.success_rate == 50.0

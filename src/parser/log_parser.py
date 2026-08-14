"""
NGINX JSON 로그 한 줄을 파싱하여 정규화된 dict로 변환.
파싱 실패 줄은 skip하고 통계를 기록.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import parse_qs

logger = logging.getLogger(__name__)


@dataclass
class ParsedLog:
    time: str
    remote_addr: str
    method: str
    uri: str
    query_string: str
    status: int
    body_bytes_sent: int
    request_length: int
    request_time: float
    http_user_agent: str
    http_referer: str
    http_x_forwarded_for: str
    http_authorization: str
    http_content_type: str
    http_accept: str
    upstream_response_time: Optional[float]
    host: str
    request_id: str

    # 파생 필드
    query_params: dict = field(default_factory=dict)
    has_auth: bool = False
    auth_type: str = ""

    @classmethod
    def from_db_row(cls, row: dict) -> "ParsedLog":
        qs = row.get("query_string") or ""
        query_params = {}
        if qs and qs != "-":
            try:
                query_params = {k: v for k, v in parse_qs(qs).items()}
            except Exception:
                pass
        return cls(
            time=row.get("time", ""),
            remote_addr=row.get("remote_addr", ""),
            method=(row.get("method") or "").upper(),
            uri=row.get("uri", ""),
            query_string=qs,
            status=int(row.get("status") or 0),
            body_bytes_sent=int(row.get("body_bytes_sent") or 0),
            request_length=int(row.get("request_length") or 0),
            request_time=float(row.get("request_time") or 0.0),
            http_user_agent=row.get("http_user_agent") or "",
            http_referer="-",
            http_x_forwarded_for="-",
            http_authorization=row.get("http_authorization") or "-",
            http_content_type="-",
            http_accept="-",
            upstream_response_time=row.get("upstream_response_time"),
            host=row.get("host") or "",
            request_id=row.get("request_id") or "",
            query_params=query_params,
            has_auth=bool(row.get("has_auth", 0)),
            auth_type=row.get("auth_type") or "",
        )

    @classmethod
    def from_dict(cls, data: dict) -> "ParsedLog":
        upstream_raw = data.get("upstream_response_time", "-")
        try:
            upstream = float(upstream_raw) if upstream_raw not in ("-", "", "None") else None
        except (ValueError, TypeError):
            upstream = None

        query_string = data.get("query_string", "")
        query_params = {}
        if query_string and query_string != "-":
            try:
                query_params = {k: v for k, v in parse_qs(query_string).items()}
            except Exception:
                pass

        auth_header = data.get("http_authorization", "-") or "-"
        has_auth = auth_header not in ("-", "", "None")
        auth_type = auth_header.split()[0] if has_auth and " " in auth_header else ("token" if has_auth else "")

        return cls(
            time=data.get("time", ""),
            remote_addr=data.get("remote_addr", ""),
            method=data.get("method", "").upper(),
            uri=data.get("uri", ""),
            query_string=query_string,
            status=int(data.get("status", 0)),
            body_bytes_sent=int(data.get("body_bytes_sent", 0)),
            request_length=int(data.get("request_length", 0)),
            request_time=float(data.get("request_time", 0.0)),
            http_user_agent=data.get("http_user_agent", ""),
            http_referer=data.get("http_referer", "-"),
            http_x_forwarded_for=data.get("http_x_forwarded_for", "-"),
            http_authorization=auth_header,
            http_content_type=data.get("http_content_type", "-"),
            http_accept=data.get("http_accept", "-"),
            upstream_response_time=upstream,
            host=data.get("host", ""),
            request_id=data.get("request_id", ""),
            query_params=query_params,
            has_auth=has_auth,
            auth_type=auth_type,
        )


@dataclass
class ParseStats:
    total: int = 0
    success: int = 0
    failed: int = 0

    @property
    def success_rate(self) -> float:
        return (self.success / self.total * 100) if self.total else 0.0


class LogParser:
    def __init__(self):
        self.stats = ParseStats()

    def parse_line(self, raw: str) -> Optional[ParsedLog]:
        self.stats.total += 1
        try:
            data = json.loads(raw)
            parsed = ParsedLog.from_dict(data)
            self.stats.success += 1
            return parsed
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self.stats.failed += 1
            logger.debug(f"Parse failed: {e} | raw: {raw[:120]}")
            return None

    def parse_batch(self, lines: list[str]) -> list[ParsedLog]:
        results = []
        for line in lines:
            parsed = self.parse_line(line)
            if parsed:
                results.append(parsed)
        return results

    def reset_stats(self):
        self.stats = ParseStats()

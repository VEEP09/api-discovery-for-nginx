"""
ParsedLog 한 건에서 원시 feature dict를 추출.
수치형/범주형 분리 없이 먼저 의미 있는 값들만 꺼내고,
인코딩/스케일링은 vectorizer가 담당.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.parser.log_parser import ParsedLog

# User-Agent 패턴
_BOT_PATTERN = re.compile(
    r"(bot|crawler|spider|scan|python-requests|curl|wget|scrapy|nmap|nikto|sqlmap|masscan)",
    re.IGNORECASE,
)
_BROWSER_PATTERN = re.compile(r"(Mozilla|Chrome|Safari|Firefox|Edge)", re.IGNORECASE)

# URI 내 특수문자 (SQL Injection, Path Traversal 등 의심 문자 포함)
_SPECIAL_CHARS = re.compile(r"[^a-zA-Z0-9/\-_.]")
_SUSPICIOUS_CHARS = re.compile(r"['\";|&<>(){}\\]|\.\.\/|%[0-9a-fA-F]{2}")


@dataclass
class RawFeatures:
    # --- 시간 ---
    hour: int                   # 0~23
    minute: int                 # 0~59
    day_of_week: int            # 0=월, 6=일
    is_weekend: int             # 0/1

    # --- 요청 기본 ---
    method: str                 # GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS
    status: int
    status_class: int           # 2, 3, 4, 5 (백의 자리)
    is_error: int               # 4xx/5xx = 1
    body_bytes_sent: int
    request_length: int
    request_time: float
    upstream_response_time: float

    # --- URI ---
    uri_length: int
    uri_depth: int              # /a/b/c → 3
    uri_special_char_ratio: float
    uri_suspicious_char_count: int
    has_path_param: int         # {id}, {uuid} 등 포함 여부
    normalized_uri: str
    api_version: str

    # --- Query String ---
    query_param_count: int
    query_total_length: int
    query_special_char_ratio: float
    query_suspicious_char_count: int

    # --- 인증 ---
    has_auth: int               # 0/1
    auth_type: str              # Bearer, Basic, token, ""

    # --- User-Agent ---
    is_bot: int
    is_browser: int
    ua_length: int

    # --- IP ---
    remote_addr: str
    is_internal_ip: int         # 10.x, 172.16~31.x, 192.168.x

    # --- 기타 ---
    request_id: str
    time_raw: str


def _safe_ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator > 0 else 0.0


def _is_internal(ip: str) -> int:
    return int(
        ip.startswith("10.")
        or ip.startswith("192.168.")
        or any(ip.startswith(f"172.{i}.") for i in range(16, 32))
        or ip in ("127.0.0.1", "::1")
    )


def _parse_time(time_str: str):
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(time_str[:19], fmt.replace("%z", ""))
        except ValueError:
            continue
    return None


class FeatureExtractor:
    def __init__(self, normalizer=None):
        """
        normalizer: URINormalizer 인스턴스.
        None이면 URI 정규화 없이 원본 사용.
        """
        self.normalizer = normalizer

    def extract(self, log: ParsedLog) -> Optional[RawFeatures]:
        dt = _parse_time(log.time)
        if dt is None:
            return None

        normalized_uri = (
            self.normalizer.normalize(log.uri) if self.normalizer else log.uri
        )
        api_version = (
            self.normalizer.extract_version(log.uri) if self.normalizer else ""
        )

        # URI 분석
        uri_segments = [s for s in normalized_uri.split("/") if s]
        uri_special = len(_SPECIAL_CHARS.findall(log.uri))
        uri_suspicious = len(_SUSPICIOUS_CHARS.findall(log.uri))
        has_path_param = int("{" in normalized_uri)

        # Query 분석
        qs = log.query_string if log.query_string not in ("-", "") else ""
        qs_special = len(_SPECIAL_CHARS.findall(qs))
        qs_suspicious = len(_SUSPICIOUS_CHARS.findall(qs))
        query_params = log.query_params

        # User-Agent
        ua = log.http_user_agent
        is_bot = int(bool(_BOT_PATTERN.search(ua)))
        is_browser = int(bool(_BROWSER_PATTERN.search(ua))) if not is_bot else 0

        # upstream_response_time 기본값
        upstream = log.upstream_response_time if log.upstream_response_time is not None else 0.0

        return RawFeatures(
            # 시간
            hour=dt.hour,
            minute=dt.minute,
            day_of_week=dt.weekday(),
            is_weekend=int(dt.weekday() >= 5),
            # 요청
            method=log.method,
            status=log.status,
            status_class=log.status // 100,
            is_error=int(log.status >= 400),
            body_bytes_sent=log.body_bytes_sent,
            request_length=log.request_length,
            request_time=log.request_time,
            upstream_response_time=upstream,
            # URI
            uri_length=len(log.uri),
            uri_depth=len(uri_segments),
            uri_special_char_ratio=_safe_ratio(uri_special, len(log.uri)),
            uri_suspicious_char_count=uri_suspicious,
            has_path_param=has_path_param,
            normalized_uri=normalized_uri,
            api_version=api_version,
            # Query
            query_param_count=len(query_params),
            query_total_length=len(qs),
            query_special_char_ratio=_safe_ratio(qs_special, len(qs)) if qs else 0.0,
            query_suspicious_char_count=qs_suspicious,
            # 인증
            has_auth=int(log.has_auth),
            auth_type=log.auth_type,
            # UA
            is_bot=is_bot,
            is_browser=is_browser,
            ua_length=len(ua),
            # IP
            remote_addr=log.remote_addr,
            is_internal_ip=_is_internal(log.remote_addr),
            # 기타
            request_id=log.request_id,
            time_raw=log.time,
        )

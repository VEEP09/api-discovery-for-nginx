"""
정규화된 (method, endpoint) 쌍을 집계하여 API Inventory를 생성.
CSV / JSON 두 가지 포맷으로 저장.
"""

import csv
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.parser.log_parser import ParsedLog

logger = logging.getLogger(__name__)

EndpointKey = Tuple[str, str]  # (method, normalized_uri)


@dataclass
class EndpointStat:
    method: str
    endpoint: str
    call_count: int = 0
    status_2xx: int = 0
    status_3xx: int = 0
    status_4xx: int = 0
    status_5xx: int = 0
    avg_response_time: float = 0.0
    has_auth: bool = False
    auth_types: set = field(default_factory=set)
    unique_ips: set = field(default_factory=set)
    domains: set = field(default_factory=set)
    first_seen: str = ""
    last_seen: str = ""
    api_version: str = ""

    # 내부 누적용 (직렬화 제외)
    _total_response_time: float = field(default=0.0, repr=False, compare=False)

    def update(self, log: ParsedLog):
        self.call_count += 1

        if 200 <= log.status < 300:
            self.status_2xx += 1
        elif 300 <= log.status < 400:
            self.status_3xx += 1
        elif 400 <= log.status < 500:
            self.status_4xx += 1
        elif 500 <= log.status < 600:
            self.status_5xx += 1

        self._total_response_time += log.request_time
        self.avg_response_time = round(self._total_response_time / self.call_count, 4)

        if log.has_auth:
            self.has_auth = True
            self.auth_types.add(log.auth_type)

        self.unique_ips.add(log.remote_addr)
        if log.host:
            self.domains.add(log.host)

        if not self.first_seen or log.time < self.first_seen:
            self.first_seen = log.time
        if not self.last_seen or log.time > self.last_seen:
            self.last_seen = log.time

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "endpoint": self.endpoint,
            "api_version": self.api_version,
            "call_count": self.call_count,
            "status_2xx": self.status_2xx,
            "status_3xx": self.status_3xx,
            "status_4xx": self.status_4xx,
            "status_5xx": self.status_5xx,
            "error_rate": round((self.status_4xx + self.status_5xx) / self.call_count * 100, 2) if self.call_count else 0,
            "avg_response_time": self.avg_response_time,
            # 백분위는 SQL 집계 경로(load_aggregates)에서 채워진다. 스트리밍 폴백
            # 경로에서는 전체 값 버퍼링이 필요해 0.0으로 두고 스키마만 맞춘다.
            "p50_response_time": 0.0,
            "p95_response_time": 0.0,
            "p99_response_time": 0.0,
            "has_auth": self.has_auth,
            "auth_types": list(self.auth_types),
            "unique_ip_count": len(self.unique_ips),
            "domains": sorted(self.domains),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }


class APIInventory:
    def __init__(self, min_call_count: int = 1):
        self.min_call_count = min_call_count
        self._endpoints: Dict[EndpointKey, EndpointStat] = defaultdict(
            lambda: EndpointStat(method="", endpoint="")
        )
        # SQL 집계로 미리 만든 dict 목록 (있으면 이 경로를 사용).
        self._prebuilt: Optional[List[dict]] = None

    def add(self, log: ParsedLog, normalized_uri: str, api_version: str = ""):
        key: EndpointKey = (log.method, normalized_uri)
        stat = self._endpoints[key]
        if not stat.method:
            stat.method = log.method
            stat.endpoint = normalized_uri
            stat.api_version = api_version
        stat.update(log)

    def load_aggregates(self, rows: List[dict]):
        """LogStore.aggregate_inventory()가 만든 집계 dict를 그대로 주입한다.

        수백만 행을 파이썬으로 순회(add)하는 대신 SQL 집계 결과를 쓴다.
        스키마는 EndpointStat.to_dict()와 동일하다고 가정한다.
        """
        self._prebuilt = rows

    def get_inventory(self) -> List[dict]:
        if self._prebuilt is not None:
            return [
                d for d in self._prebuilt
                if d.get("call_count", 0) >= self.min_call_count
            ]
        return [
            stat.to_dict()
            for stat in self._endpoints.values()
            if stat.call_count >= self.min_call_count
        ]

    def save(self, output_dir: str, fmt: str = "both"):
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        inventory = self.get_inventory()

        if not inventory:
            logger.warning("No API inventory to save")
            return

        if fmt in ("json", "both"):
            json_path = path / f"api_inventory_{timestamp}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(inventory, f, ensure_ascii=False, indent=2)
            logger.info(f"JSON saved: {json_path}")

        if fmt in ("csv", "both"):
            csv_path = path / f"api_inventory_{timestamp}.csv"
            fieldnames = list(inventory[0].keys())
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for row in inventory:
                    row["auth_types"] = "|".join(row["auth_types"])
                    writer.writerow(row)
            logger.info(f"CSV saved: {csv_path}")

    @property
    def total_endpoints(self) -> int:
        if self._prebuilt is not None:
            return len(self._prebuilt)
        return len(self._endpoints)

    @property
    def total_calls(self) -> int:
        if self._prebuilt is not None:
            return sum(d.get("call_count", 0) for d in self._prebuilt)
        return sum(s.call_count for s in self._endpoints.values())

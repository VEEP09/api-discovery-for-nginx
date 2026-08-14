"""
output/ 디렉토리에서 가장 최신 파이프라인 결과물을 읽어 대시보드에 제공.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl

from src.discovery.openapi_parser import OpenAPISpec, parse_spec
from src.discovery.shadow_detector import ShadowDetectionResult, detect

# 정적 리소스(.js/.css/맵/폰트/이미지)는 API가 아니므로 인벤토리에서 제외한다.
# 에이전트가 이미 대부분 걸러내지만 .js 등이 새어 들어온 경우 대시보드에서 방어.
_STATIC_EXT = (
    ".js", ".mjs", ".cjs", ".css", ".map", ".ico", ".png", ".jpg", ".jpeg",
    ".gif", ".svg", ".webp", ".avif", ".bmp", ".woff", ".woff2", ".ttf", ".eot",
)


def _is_static_asset(endpoint: str) -> bool:
    path = (endpoint or "").split("?", 1)[0].lower()
    return path.endswith(_STATIC_EXT)


class OutputReader:
    # COUNT(*) 캐시 유지 시간(초). 대시보드 표시용 총계라 짧은 staleness 허용.
    _COUNT_TTL = 60.0

    def __init__(self, output_dir: str = "./output"):
        self.output_dir = Path(output_dir)
        self.models_dir = self.output_dir / "models"
        self.openapi_dir = self.output_dir / "openapi"
        self.openapi_dir.mkdir(parents=True, exist_ok=True)

        # ── 캐시 ──────────────────────────────────────────
        # 샘플: inventory JSON의 (경로, mtime)을 키로 사용 → 파이프라인이
        #   하루 1회 inventory를 재생성할 때만 자동 무효화(=하루 1회 갱신).
        self._samples_cache: Optional[dict] = None
        self._samples_cache_key: Optional[tuple] = None
        # 총 요청 수: 시간 기반 TTL 캐시.
        self._count_cache: Optional[int] = None
        self._count_cache_ts: float = 0.0
        # OpenAPI 스펙: (경로, mtime) 기준 캐시 → 업로드 시에만 재파싱.
        self._spec_cache: Optional[OpenAPISpec] = None
        self._spec_cache_key: Optional[tuple] = None

    def _latest(self, pattern: str) -> Optional[Path]:
        files = sorted(self.output_dir.glob(pattern))
        return files[-1] if files else None

    def get_inventory(self, attach_samples: bool = False) -> list:
        path = self._latest("api_inventory_*.json")
        if not path:
            return []
        with open(path) as f:
            inventory = json.load(f)
        # 정적 리소스(.js 등)는 API가 아니므로 모든 뷰에서 일관되게 제외
        inventory = [e for e in inventory if not _is_static_asset(e.get("endpoint", ""))]
        if attach_samples:
            self._attach_sample_requests(inventory)
        return inventory

    def _attach_sample_requests(self, inventory: list):
        """최근 성공 로그의 실제 URI/query를 inventory 항목에 붙인다."""
        samples = self._cached_request_samples()
        if not samples:
            return

        for entry in inventory:
            method = (entry.get("method") or "").upper()
            endpoint = entry.get("endpoint") or ""
            sample_requests = {}
            for domain in entry.get("domains") or []:
                sample = samples.get((method, endpoint, domain))
                if sample:
                    sample_requests[domain] = sample

            if sample_requests:
                entry["sample_requests"] = sample_requests
                first_domain = next(
                    (domain for domain in entry.get("domains") or [] if domain in sample_requests),
                    None,
                )
                if first_domain:
                    entry["sample_request"] = sample_requests[first_domain]

    def _cached_request_samples(self) -> dict:
        """샘플 추출 결과를 inventory JSON의 (경로, mtime) 기준으로 캐시.

        샘플 계산은 api_logs 전체를 GROUP BY 스캔하므로 행 수에 비례해 비싸다.
        결과가 바뀌는 시점은 사실상 파이프라인이 inventory를 재생성할 때(하루 1회)
        뿐이므로, inventory 파일의 mtime이 바뀔 때만 재계산한다.
        """
        inv_path = self._latest("api_inventory_*.json")
        key = (str(inv_path), inv_path.stat().st_mtime) if inv_path else None

        if self._samples_cache is not None and key == self._samples_cache_key:
            return self._samples_cache

        samples = self._latest_request_samples()
        self._samples_cache = samples
        self._samples_cache_key = key
        return samples

    def _latest_request_samples(self) -> dict:
        db_path = self.output_dir / "api_logs.db"
        if not db_path.exists():
            return {}

        # (method, normalized_uri, host) 조합별로 대표 1건만 선별.
        # 대표는 "가장 최신 성공(2xx/3xx) 요청"을 우선하고, 성공 이력이 없으면
        # 최신 요청으로 폴백한다. 샘플은 대시보드 Try-it-out 프리필용이라
        # 404 같은 실패 요청(존재하지 않는 경로·빈 쿼리)을 잡으면 무용지물이기 때문.
        # 서브쿼리로 조합별 대표 id만 먼저 추린 뒤 JOIN하여,
        # 전체 행을 Python으로 순회하지 않고 조합 수(수백 건)만 가져온다.
        # 여전히 index 기반 단일 GROUP BY라 전체 스캔을 유발하지 않는다.
        query = """
            SELECT a.id, a.time, a.method, a.normalized_uri, a.host,
                   a.uri, a.query_string, a.status, a.http_authorization
            FROM api_logs a
            JOIN (
                SELECT COALESCE(
                         MAX(CASE WHEN status BETWEEN 200 AND 399 THEN id END),
                         MAX(id)
                       ) AS mid
                FROM api_logs
                WHERE method != ''
                  AND normalized_uri != ''
                  AND host != ''
                GROUP BY method, normalized_uri, host
            ) b ON a.id = b.mid
        """

        samples = {}
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(query)
                for row in rows:
                    key = (
                        (row["method"] or "").upper(),
                        row["normalized_uri"] or "",
                        row["host"] or "",
                    )
                    if key in samples:
                        continue

                    qs = row["query_string"] or ""
                    query_params = {
                        k: v for k, v in parse_qsl(qs, keep_blank_values=True)
                    } if qs and qs != "-" else {}
                    auth_header = row["http_authorization"] or ""

                    samples[key] = {
                        "path": row["uri"] or row["normalized_uri"] or "/",
                        "query": query_params,
                        "status": int(row["status"] or 0),
                        "last_seen": row["time"] or "",
                        "has_authorization": auth_header not in ("", "-", "None"),
                    }
        except sqlite3.Error:
            return {}
        return samples

    def get_feature_stats(self) -> dict:
        path = self._latest("feature_stats_*.json")
        if not path:
            return {}
        with open(path) as f:
            return json.load(f)

    def get_ae_threshold(self) -> dict:
        path = self.models_dir / "ae_threshold.json"
        if not path.exists():
            return {}
        with open(path) as f:
            return json.load(f)

    def get_lstm_threshold(self) -> dict:
        path = self.models_dir / "lstm_threshold.json"
        if not path.exists():
            return {}
        with open(path) as f:
            return json.load(f)

    def get_ae_history(self) -> list:
        path = self.models_dir / "ae_train_history.json"
        if not path.exists():
            return []
        with open(path) as f:
            return json.load(f)

    def get_lstm_history(self) -> list:
        path = self.models_dir / "lstm_train_history.json"
        if not path.exists():
            return []
        with open(path) as f:
            return json.load(f)

    # ── OpenAPI ──────────────────────────────────────────

    def get_openapi_spec_path(self) -> Optional[Path]:
        """가장 최근에 업로드된 스펙 파일 경로."""
        for ext in ("*.yaml", "*.yml", "*.json"):
            files = sorted(self.openapi_dir.glob(ext))
            if files:
                return files[-1]
        return None

    def get_openapi_spec(self) -> Optional[OpenAPISpec]:
        path = self.get_openapi_spec_path()
        if not path:
            return None
        # 스펙 파싱은 매 호출 ~0.5s. 업로드 시에만 바뀌므로 (경로, mtime) 기준 캐시.
        key = (str(path), path.stat().st_mtime)
        if self._spec_cache_key == key:
            return self._spec_cache
        try:
            spec = parse_spec(str(path))
        except Exception:
            spec = None
        self._spec_cache = spec
        self._spec_cache_key = key
        return spec

    def get_openapi_info(self) -> dict:
        spec = self.get_openapi_spec()
        if not spec:
            return {"uploaded": False}
        return {
            "uploaded": True,
            "title": spec.title,
            "version": spec.version,
            "openapi_version": spec.openapi_version,
            "base_path": spec.base_path,
            "endpoint_count": spec.endpoint_count,
            "file_name": Path(spec.raw_path).name,
        }

    def get_shadow_result(self, inventory: Optional[list] = None) -> ShadowDetectionResult:
        if inventory is None:
            inventory = self.get_inventory()
        spec = self.get_openapi_spec()
        return detect(inventory, spec)

    def _load_fixed(self, name: str) -> list:
        path = self.output_dir / name
        if not path.exists():
            return []
        with open(path) as f:
            return json.load(f)

    def get_ml_endpoints(self) -> list:
        return self._load_fixed("ml_endpoint_anomaly.json")

    def get_suspicious_ips(self) -> list:
        return self._load_fixed("suspicious_ips.json")

    def get_time_anomalies(self) -> list:
        return self._load_fixed("time_anomaly.json")

    # ── Summary ──────────────────────────────────────────

    def _db_total_requests(self) -> int:
        # COUNT(*)는 SQLite에서 전체 스캔이라 행 수에 비례해 느리다(250만 행 ≈ 0.4s).
        # 대시보드 표시용 총계이므로 _COUNT_TTL 동안 캐시한다.
        now = time.monotonic()
        if self._count_cache is not None and (now - self._count_cache_ts) < self._COUNT_TTL:
            return self._count_cache

        db_path = self.output_dir / "api_logs.db"
        if not db_path.exists():
            return 0
        try:
            with sqlite3.connect(db_path) as conn:
                total = conn.execute("SELECT COUNT(*) FROM api_logs").fetchone()[0]
        except sqlite3.Error:
            return 0

        self._count_cache = total
        self._count_cache_ts = now
        return total

    def summary(self) -> dict:
        inventory = self.get_inventory()
        stats = self.get_feature_stats()
        ae = self.get_ae_threshold()
        lstm = self.get_lstm_threshold()
        shadow_result = self.get_shadow_result(inventory=inventory)

        total_calls = self._db_total_requests()
        total_errors = sum(e.get("status_4xx", 0) + e.get("status_5xx", 0) for e in inventory)
        auth_required = sum(1 for e in inventory if e.get("has_auth"))
        no_auth = [e for e in inventory if not e.get("has_auth")]
        risky = [e for e in inventory if e.get("error_rate", 0) >= 30]

        first_seen_vals = [e["first_seen"] for e in inventory if e.get("first_seen")]
        last_seen_vals  = [e["last_seen"]  for e in inventory if e.get("last_seen")]

        return {
            "data_from": min(first_seen_vals) if first_seen_vals else None,
            "data_to":   max(last_seen_vals)  if last_seen_vals  else None,
            "total_endpoints": len(inventory),
            "total_calls": total_calls,
            "total_errors": total_errors,
            "global_error_rate": round(total_errors / total_calls * 100, 2) if total_calls else 0,
            "auth_required_count": auth_required,
            "no_auth_count": len(no_auth),
            "risky_endpoint_count": len(risky),
            "shadow_count": len(shadow_result.shadow_endpoints),
            "shadow_spec_count": sum(
                1 for s in shadow_result.shadow_endpoints if "spec" in s.source
            ),
            "unused_spec_count": len(shadow_result.unused_endpoints),
            "unique_ips": stats.get("unique_ips", 0),
            "total_sequences": stats.get("total_sequences", 0),
            "ae_threshold": ae.get("threshold"),
            "lstm_threshold": lstm.get("threshold"),
            "model_trained": bool(ae),
            "spec_uploaded": shadow_result.has_spec,
        }

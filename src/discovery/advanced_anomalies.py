"""
고급 이상 탐지 (ML 모델 출력 + 규칙 기반 보조):
1. aggregate_ml_endpoints  — AE 출력을 엔드포인트 단위로 집계
2. aggregate_suspicious_ips — LSTM 출력을 IP 단위로 집계
3. detect_time_anomalies   — 엔드포인트별 off-hour 요청 탐지

모두 min_call_count 기준을 존중 (단발성 노이즈 제거).
"""

from collections import defaultdict
from typing import Dict, List, Tuple


def aggregate_ml_endpoints(
    ae_results: list,
    domain_map: Dict[Tuple[str, str], List[str]] = None,
    min_call_count: int = 10,
) -> List[dict]:
    """AE AnomalyResult 리스트를 (method, normalized_uri) 단위로 집계."""
    domain_map = domain_map or {}
    buckets = defaultdict(lambda: {"total": 0, "anomalous": 0, "max_score": 0.0})

    for r in ae_results:
        if not r.method or not r.normalized_uri:
            continue
        key = (r.method, r.normalized_uri)
        b = buckets[key]
        b["total"] += 1
        if r.is_anomaly:
            b["anomalous"] += 1
        if r.score > b["max_score"]:
            b["max_score"] = r.score

    out = []
    for (method, endpoint), b in buckets.items():
        if b["total"] < min_call_count:
            continue
        if b["anomalous"] == 0:
            continue
        out.append({
            "method": method,
            "endpoint": endpoint,
            "domains": domain_map.get((method, endpoint), []),
            "total_requests": b["total"],
            "anomalous_requests": b["anomalous"],
            "anomaly_ratio": round(b["anomalous"] / b["total"] * 100, 2),
            "max_score": round(b["max_score"], 6),
        })
    out.sort(key=lambda x: x["anomaly_ratio"], reverse=True)
    return out


def aggregate_suspicious_ips(lstm_results: list, min_sequences: int = 3) -> List[dict]:
    """LSTM AnomalyResult를 IP 단위로 집계. min_sequences 미만은 제외."""
    buckets = defaultdict(
        lambda: {"total": 0, "anomalous": 0, "max_score": 0.0, "last_seen": ""}
    )

    for r in lstm_results:
        ip = r.remote_addr or ""
        if not ip:
            continue
        b = buckets[ip]
        b["total"] += 1
        if r.is_anomaly:
            b["anomalous"] += 1
        if r.score > b["max_score"]:
            b["max_score"] = r.score
        if r.time_raw and r.time_raw > b["last_seen"]:
            b["last_seen"] = r.time_raw

    out = []
    for ip, b in buckets.items():
        if b["total"] < min_sequences:
            continue
        if b["anomalous"] == 0:
            continue
        out.append({
            "ip": ip,
            "total_sequences": b["total"],
            "anomalous_sequences": b["anomalous"],
            "anomaly_ratio": round(b["anomalous"] / b["total"] * 100, 2),
            "max_score": round(b["max_score"], 6),
            "last_seen": b["last_seen"],
        })
    out.sort(key=lambda x: x["anomaly_ratio"], reverse=True)
    return out


def detect_time_anomalies(
    raw_features: list,
    domain_map: Dict[Tuple[str, str], List[str]] = None,
    min_call_count: int = 10,
    rare_threshold: float = 0.03,
    core_threshold: float = 0.10,
) -> List[dict]:
    """
    엔드포인트별 hour(0-23) 분포를 분석.
    - core_hours: 전체 요청의 10%+ 를 차지하는 시간대
    - rare hours: 3% 미만의 비중이지만 실제 요청이 발생한 시간대 → off-hour
    """
    domain_map = domain_map or {}
    hour_buckets: Dict[Tuple[str, str], Dict[int, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    for f in raw_features:
        key = (f.method, f.normalized_uri)
        hour_buckets[key][f.hour] += 1

    out = []
    for (method, endpoint), hours in hour_buckets.items():
        total = sum(hours.values())
        if total < min_call_count:
            continue

        core = sorted([h for h, c in hours.items() if c / total >= core_threshold])
        rare = {h for h, c in hours.items() if 0 < c / total < rare_threshold}

        off_count = sum(hours[h] for h in rare)
        if off_count == 0:
            continue

        out.append({
            "method": method,
            "endpoint": endpoint,
            "domains": domain_map.get((method, endpoint), []),
            "total_requests": total,
            "core_hours": core,
            "rare_hours": sorted(rare),
            "off_hour_requests": off_count,
            "off_hour_ratio": round(off_count / total * 100, 2),
        })
    out.sort(key=lambda x: x["off_hour_ratio"], reverse=True)
    return out

"""
학습된 모델로 이상 점수를 산출하고 임계값 기반으로 이상/정상을 판정.

임계값 결정 전략:
- percentile: 정상 데이터의 상위 N% 오차를 임계값으로 설정
- fixed: 직접 지정
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import torch
import torch.nn as nn
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class AnomalyResult:
    index: int
    score: float
    is_anomaly: bool
    threshold: float
    # 메타 정보 (extractor에서 가져온 원본 필드)
    remote_addr: str = ""
    method: str = ""
    normalized_uri: str = ""
    time_raw: str = ""
    request_id: str = ""


@dataclass
class DetectionSummary:
    model_type: str
    total: int
    anomaly_count: int
    threshold: float
    percentile_used: float
    results: List[AnomalyResult] = field(default_factory=list)

    @property
    def anomaly_rate(self) -> float:
        return round(self.anomaly_count / self.total * 100, 2) if self.total else 0.0


class AnomalyDetector:
    def __init__(
        self,
        model: nn.Module,
        threshold_percentile: float = 95.0,
        device: Optional[str] = None,
    ):
        self.model = model
        self.threshold_percentile = threshold_percentile
        self.threshold: Optional[float] = None
        self.device = torch.device(
            device if device else ("cuda" if torch.cuda.is_available() else "cpu")
        )
        self.model.to(self.device)
        self.model.eval()

    def fit_threshold(self, normal_data: torch.Tensor):
        """정상 데이터로 임계값 결정. 학습 후 한 번 호출."""
        scores = self._compute_scores(normal_data)
        self.threshold = float(np.percentile(scores, self.threshold_percentile))
        logger.info(f"Threshold set: {self.threshold:.6f} "
                    f"({self.threshold_percentile}th percentile of normal data)")

    def detect(
        self,
        data: torch.Tensor,
        meta: Optional[List[dict]] = None,
    ) -> DetectionSummary:
        """
        data: 추론할 텐서
        meta: 각 샘플의 메타 정보 dict 리스트 (remote_addr, method 등)
        """
        if self.threshold is None:
            raise RuntimeError("fit_threshold()를 먼저 호출하세요.")

        scores = self._compute_scores(data)
        results = []
        for i, score in enumerate(scores):
            m = meta[i] if meta else {}
            results.append(AnomalyResult(
                index=i,
                score=round(float(score), 6),
                is_anomaly=float(score) > self.threshold,
                threshold=self.threshold,
                remote_addr=m.get("remote_addr", ""),
                method=m.get("method", ""),
                normalized_uri=m.get("normalized_uri", ""),
                time_raw=m.get("time_raw", ""),
                request_id=m.get("request_id", ""),
            ))

        anomaly_count = sum(1 for r in results if r.is_anomaly)
        summary = DetectionSummary(
            model_type=type(self.model).__name__,
            total=len(results),
            anomaly_count=anomaly_count,
            threshold=self.threshold,
            percentile_used=self.threshold_percentile,
            results=results,
        )
        logger.info(f"Detection finished: {summary.anomaly_count} anomalies out of {summary.total} "
                    f"(rate: {summary.anomaly_rate}%)")
        return summary

    def _compute_scores(self, data: torch.Tensor) -> np.ndarray:
        with torch.no_grad():
            data = data.to(self.device)
            scores = self.model.reconstruction_error(data)
        return scores.cpu().numpy()

    def save_threshold(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump({
                "threshold": self.threshold,
                "percentile": self.threshold_percentile,
            }, f, indent=2)
        logger.info(f"Threshold saved: {path}")

    def load_threshold(self, path: str):
        with open(path) as f:
            data = json.load(f)
        self.threshold = data["threshold"]
        self.threshold_percentile = data["percentile"]
        logger.info(f"Threshold loaded: {self.threshold:.6f} ({path})")

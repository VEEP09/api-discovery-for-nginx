"""
RawFeatures → 수치 벡터 변환.

- 범주형 (method, auth_type): Label Encoding (fit 기반)
- 수치형: MinMax Scaling (fit 기반)
- fit() → transform() 순서로 사용
- 학습된 인코더/스케일러는 save/load로 재사용 (서버 간 일관성 보장)
"""

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.features.extractor import RawFeatures

logger = logging.getLogger(__name__)

# AutoEncoder에 사용할 수치형 feature 목록 (순서 고정)
NUMERIC_FEATURES = [
    "hour",
    "minute",
    "day_of_week",
    "is_weekend",
    "status_class",
    "is_error",
    "body_bytes_sent",
    "request_length",
    "request_time",
    "upstream_response_time",
    "uri_length",
    "uri_depth",
    "uri_special_char_ratio",
    "uri_suspicious_char_count",
    "has_path_param",
    "query_param_count",
    "query_total_length",
    "query_special_char_ratio",
    "query_suspicious_char_count",
    "has_auth",
    "is_bot",
    "is_browser",
    "ua_length",
    "is_internal_ip",
    # 인코딩된 범주형 (아래에서 추가)
    "method_encoded",
    "auth_type_encoded",
]

CATEGORICAL_FEATURES = {
    "method": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    "auth_type": ["", "Bearer", "Basic", "token"],
}


class FeatureVectorizer:
    def __init__(self):
        self._label_encoders: Dict[str, Dict[str, int]] = {}
        self._min_vals: Dict[str, float] = {}
        self._max_vals: Dict[str, float] = {}
        self._fitted = False

    def fit(self, features_list: List[RawFeatures]):
        # 범주형: 사전 정의된 값 + 실제 데이터에서 발견된 미지 값 포함
        for col, known_values in CATEGORICAL_FEATURES.items():
            seen = set(known_values)
            for f in features_list:
                seen.add(getattr(f, col))
            self._label_encoders[col] = {v: i for i, v in enumerate(sorted(seen))}

        # 수치형: min/max 계산 (범주형 인코딩 후 포함)
        encoded = [self._encode_categorical(f) for f in features_list]
        numeric_cols = [c for c in NUMERIC_FEATURES if not c.endswith("_encoded")]
        numeric_cols += ["method_encoded", "auth_type_encoded"]

        all_cols = [c for c in NUMERIC_FEATURES]
        for col in all_cols:
            vals = [row.get(col, 0) for row in encoded]
            self._min_vals[col] = float(min(vals))
            self._max_vals[col] = float(max(vals))

        self._fitted = True
        logger.info(f"Vectorizer fitted: {len(features_list)} samples, "
                    f"{len(NUMERIC_FEATURES)} features")

    def transform(self, features: RawFeatures) -> List[float]:
        if not self._fitted:
            raise RuntimeError("fit()을 먼저 호출하세요.")
        row = self._encode_categorical(features)
        return [self._scale(col, row.get(col, 0)) for col in NUMERIC_FEATURES]

    def fit_transform(self, features_list: List[RawFeatures]) -> List[List[float]]:
        self.fit(features_list)
        return [self.transform(f) for f in features_list]

    def _encode_categorical(self, features: RawFeatures) -> dict:
        d = {}
        for col in NUMERIC_FEATURES:
            if col.endswith("_encoded"):
                orig_col = col[: -len("_encoded")]
                val = getattr(features, orig_col, "")
                encoder = self._label_encoders.get(orig_col, {})
                d[col] = encoder.get(val, len(encoder))  # 미지값은 마지막 인덱스
            else:
                d[col] = float(getattr(features, col, 0))
        return d

    def _scale(self, col: str, val: float) -> float:
        mn = self._min_vals.get(col, 0.0)
        mx = self._max_vals.get(col, 1.0)
        if mx == mn:
            return 0.0
        return round((val - mn) / (mx - mn), 6)

    @property
    def feature_dim(self) -> int:
        return len(NUMERIC_FEATURES)

    @property
    def feature_names(self) -> List[str]:
        return list(NUMERIC_FEATURES)

    def save(self, path: str):
        state = {
            "label_encoders": self._label_encoders,
            "min_vals": self._min_vals,
            "max_vals": self._max_vals,
            "fitted": self._fitted,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f, indent=2)
        logger.info(f"Vectorizer saved: {path}")

    def load(self, path: str):
        with open(path, "r") as f:
            state = json.load(f)
        self._label_encoders = state["label_encoders"]
        self._min_vals = {k: float(v) for k, v in state["min_vals"].items()}
        self._max_vals = {k: float(v) for k, v in state["max_vals"].items()}
        self._fitted = state["fitted"]
        logger.info(f"Vectorizer loaded: {path}")

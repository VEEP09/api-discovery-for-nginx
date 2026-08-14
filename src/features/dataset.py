"""
Feature Engineering 결과를 파일로 저장/로드.
AutoEncoder용 flat 벡터 dataset과 LSTM용 sequence dataset을 분리 저장.
"""

import csv
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Optional

from src.features.extractor import RawFeatures
from src.features.sequence_builder import Sequence
from src.features.vectorizer import NUMERIC_FEATURES

logger = logging.getLogger(__name__)


class DatasetWriter:
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    def save_flat(self, vectors: List[List[float]], features_list: List[RawFeatures]):
        """AutoEncoder용: 벡터 + 메타 정보를 CSV로 저장."""
        path = self.output_dir / f"features_flat_{self._ts}.csv"
        meta_cols = ["time_raw", "remote_addr", "method", "normalized_uri", "request_id"]
        fieldnames = meta_cols + NUMERIC_FEATURES

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for vec, feat in zip(vectors, features_list):
                row = {
                    "time_raw": feat.time_raw,
                    "remote_addr": feat.remote_addr,
                    "method": feat.method,
                    "normalized_uri": feat.normalized_uri,
                    "request_id": feat.request_id,
                }
                row.update(dict(zip(NUMERIC_FEATURES, vec)))
                writer.writerow(row)

        logger.info(f"Flat dataset saved: {path} ({len(vectors)} rows)")
        return str(path)

    def save_sequences(self, sequences: List[Sequence]):
        """LSTM용: 시퀀스 데이터를 JSON으로 저장."""
        path = self.output_dir / f"features_sequences_{self._ts}.json"
        data = [
            {
                "ip": seq.ip,
                "label": seq.label,
                "timestamps": seq.timestamps,
                "request_ids": seq.request_ids,
                "vectors": seq.vectors,
            }
            for seq in sequences
        ]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        logger.info(f"Sequence dataset saved: {path} ({len(sequences)} sequences)")
        return str(path)

    def save_stats(self, stats: dict):
        """Feature Engineering 통계 요약 저장."""
        path = self.output_dir / f"feature_stats_{self._ts}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
        logger.info(f"Statistics saved: {path}")
        return str(path)

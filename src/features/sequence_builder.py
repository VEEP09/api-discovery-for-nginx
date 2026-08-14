"""
LSTM용 시퀀스 생성.
IP 단위로 요청을 시간순 정렬 후 window_size 길이의 슬라이딩 윈도우로 자름.

출력: List[Sequence]
  - Sequence.ip: 출처 IP
  - Sequence.vectors: shape (window_size, feature_dim) 의 2D 리스트
  - Sequence.timestamps: 각 벡터의 원본 시각
  - Sequence.labels: 외부에서 라벨 주입 가능 (이상=1, 정상=0)
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from src.features.extractor import RawFeatures
from src.features.vectorizer import FeatureVectorizer

logger = logging.getLogger(__name__)


@dataclass
class Sequence:
    ip: str
    vectors: List[List[float]]   # (window_size, feature_dim)
    timestamps: List[str]
    request_ids: List[str]
    label: Optional[int] = None  # 0=정상, 1=이상 (라벨 있을 때)


class SequenceBuilder:
    def __init__(self, vectorizer: FeatureVectorizer, window_size: int = 10, step: int = 1):
        """
        window_size: 시퀀스 길이 (LSTM 입력 timestep 수)
        step: 슬라이딩 윈도우 이동 간격 (1이면 모든 윈도우, window_size면 겹침 없음)
        """
        self.vectorizer = vectorizer
        self.window_size = window_size
        self.step = step

    def build(self, features_list: List[RawFeatures]) -> List[Sequence]:
        """RawFeatures 리스트 → IP별 슬라이딩 윈도우 시퀀스."""
        ip_buckets: Dict[str, List[RawFeatures]] = defaultdict(list)
        for f in features_list:
            ip_buckets[f.remote_addr].append(f)

        sequences: List[Sequence] = []
        for ip, entries in ip_buckets.items():
            # 시간순 정렬
            entries.sort(key=lambda x: x.time_raw)

            if len(entries) < self.window_size:
                # 요청 수가 window_size보다 적으면 패딩
                seqs = self._build_padded(ip, entries)
            else:
                seqs = self._build_sliding(ip, entries)

            sequences.extend(seqs)

        logger.info(f"Built {len(sequences)} sequences "
                    f"(IPs: {len(ip_buckets)}, window={self.window_size})")
        return sequences

    def _build_sliding(self, ip: str, entries: List[RawFeatures]) -> List[Sequence]:
        seqs = []
        for start in range(0, len(entries) - self.window_size + 1, self.step):
            window = entries[start: start + self.window_size]
            vectors = [self.vectorizer.transform(f) for f in window]
            seqs.append(Sequence(
                ip=ip,
                vectors=vectors,
                timestamps=[f.time_raw for f in window],
                request_ids=[f.request_id for f in window],
            ))
        return seqs

    def _build_padded(self, ip: str, entries: List[RawFeatures]) -> List[Sequence]:
        """요청이 window_size보다 적은 IP: 앞을 0 벡터로 패딩하여 1개 시퀀스 생성."""
        vectors = [self.vectorizer.transform(f) for f in entries]
        pad_count = self.window_size - len(vectors)
        zero_vec = [0.0] * self.vectorizer.feature_dim
        padded_vectors = [zero_vec] * pad_count + vectors
        padded_ts = [""] * pad_count + [f.time_raw for f in entries]
        padded_ids = [""] * pad_count + [f.request_id for f in entries]
        return [Sequence(ip=ip, vectors=padded_vectors, timestamps=padded_ts, request_ids=padded_ids)]

    @staticmethod
    def label_sequences(sequences: List[Sequence], anomaly_ips: set) -> List[Sequence]:
        """알려진 이상 IP 목록으로 시퀀스에 라벨 주입."""
        for seq in sequences:
            seq.label = 1 if seq.ip in anomaly_ips else 0
        return sequences

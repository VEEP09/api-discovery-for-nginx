"""
모델 학습 / 저장 / 로드를 일괄 관리.
pipeline.py에서 호출되는 단일 진입점.
"""

import logging
from pathlib import Path
from typing import List, Optional

import torch

from src.features.extractor import RawFeatures
from src.features.sequence_builder import Sequence
from src.features.vectorizer import FeatureVectorizer
from src.models.autoencoder import AutoEncoder
from src.models.detector import AnomalyDetector, DetectionSummary
from src.models.lstm_model import LSTMAutoEncoder
from src.models.trainer import Trainer

logger = logging.getLogger(__name__)


class ModelManager:
    def __init__(self, config: dict, feature_dim: int, seq_len: int):
        """
        config: settings.yaml의 models 섹션
        feature_dim: vectorizer.feature_dim
        seq_len: sequence_builder.window_size
        """
        self.config = config
        self.feature_dim = feature_dim
        self.seq_len = seq_len
        self.output_dir = Path(config.get("output_dir", "./output/models"))
        self.output_dir.mkdir(parents=True, exist_ok=True)

        ae_cfg = config.get("autoencoder", {})
        self.ae_model = AutoEncoder(
            input_dim=feature_dim,
            hidden_dims=ae_cfg.get("hidden_dims", [16, 8]),
        )
        lstm_cfg = config.get("lstm", {})
        self.lstm_model = LSTMAutoEncoder(
            input_dim=feature_dim,
            hidden_dim=lstm_cfg.get("hidden_dim", 32),
            seq_len=seq_len,
            num_layers=lstm_cfg.get("num_layers", 1),
        )

    def train_autoencoder(
        self,
        vectors: List[List[float]],
        meta: Optional[List[dict]] = None,
    ) -> DetectionSummary:
        ae_cfg = self.config.get("autoencoder", {})
        data = torch.tensor(vectors, dtype=torch.float32)

        trainer = Trainer(
            model=self.ae_model,
            lr=ae_cfg.get("lr", 1e-3),
            batch_size=ae_cfg.get("batch_size", 64),
            max_epochs=ae_cfg.get("max_epochs", 100),
            patience=ae_cfg.get("patience", 10),
        )
        history = trainer.train(data)
        trainer.save_history(str(self.output_dir / "ae_train_history.json"))
        torch.save(self.ae_model.state_dict(), str(self.output_dir / "autoencoder.pt"))
        logger.info("AutoEncoder model saved")

        detector = AnomalyDetector(
            model=self.ae_model,
            threshold_percentile=self.config.get("threshold_percentile", 95.0),
        )
        detector.fit_threshold(data)
        detector.save_threshold(str(self.output_dir / "ae_threshold.json"))

        return detector.detect(data, meta=meta)

    def train_lstm(self, sequences: List[Sequence]) -> Optional[DetectionSummary]:
        if not sequences:
            logger.warning("No LSTM training data - skipped")
            return None

        lstm_cfg = self.config.get("lstm", {})
        tensor = torch.tensor(
            [seq.vectors for seq in sequences], dtype=torch.float32
        )  # (N, seq_len, feature_dim)

        trainer = Trainer(
            model=self.lstm_model,
            lr=lstm_cfg.get("lr", 1e-3),
            batch_size=lstm_cfg.get("batch_size", 32),
            max_epochs=lstm_cfg.get("max_epochs", 100),
            patience=lstm_cfg.get("patience", 10),
        )
        history = trainer.train(tensor)
        trainer.save_history(str(self.output_dir / "lstm_train_history.json"))
        torch.save(self.lstm_model.state_dict(), str(self.output_dir / "lstm_autoencoder.pt"))
        logger.info("LSTM AutoEncoder model saved")

        detector = AnomalyDetector(
            model=self.lstm_model,
            threshold_percentile=self.config.get("threshold_percentile", 95.0),
        )
        detector.fit_threshold(tensor)
        detector.save_threshold(str(self.output_dir / "lstm_threshold.json"))

        meta = [
            {
                "remote_addr": seq.ip,
                "time_raw": seq.timestamps[-1] if seq.timestamps else "",
                "request_id": seq.request_ids[-1] if seq.request_ids else "",
            }
            for seq in sequences
        ]
        return detector.detect(tensor, meta=meta)

    def load_autoencoder(self):
        path = self.output_dir / "autoencoder.pt"
        self.ae_model.load_state_dict(torch.load(str(path), weights_only=True))
        logger.info(f"AutoEncoder loaded: {path}")
        return self.ae_model

    def load_lstm(self):
        path = self.output_dir / "lstm_autoencoder.pt"
        self.lstm_model.load_state_dict(torch.load(str(path), weights_only=True))
        logger.info(f"LSTM AutoEncoder loaded: {path}")
        return self.lstm_model

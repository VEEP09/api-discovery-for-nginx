"""
전체 파이프라인 오케스트레이터.
에이전트가 /api/ingest 로 적재한 DB 데이터를 기반으로
inventory → feature engineering → model training 수행.
"""

import logging
import time
from pathlib import Path

import yaml
import json

from src.db.log_store import LogStore
from src.discovery.advanced_anomalies import (
    aggregate_ml_endpoints,
    aggregate_suspicious_ips,
    detect_time_anomalies,
)
from src.discovery.inventory import APIInventory
from src.discovery.normalizer import URINormalizer
from src.features.dataset import DatasetWriter
from src.features.extractor import FeatureExtractor
from src.features.sequence_builder import SequenceBuilder
from src.features.vectorizer import FeatureVectorizer
from src.models.model_manager import ModelManager
from src.parser.log_parser import ParsedLog

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, config_path: str = "config/settings.yaml"):
        self.config = self._load_config(config_path)
        self._setup_components()

    def _load_config(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _setup_components(self):
        cfg_pipeline = self.config["pipeline"]
        cfg_discovery = self.config["discovery"]
        cfg_inventory = self.config["inventory"]
        cfg_features = self.config.get("features", {})

        self.normalizer = URINormalizer(
            rules=cfg_discovery["normalizers"],
            exclude_prefixes=cfg_discovery.get("exclude_prefixes", []),
            exclude_extensions=cfg_discovery.get("exclude_extensions", []),
        )
        self.inventory = APIInventory(
            min_call_count=cfg_inventory["min_call_count"],
        )
        self.extractor = FeatureExtractor(normalizer=self.normalizer)
        self.vectorizer = FeatureVectorizer()
        self.sequence_builder = SequenceBuilder(
            vectorizer=self.vectorizer,
            window_size=cfg_features.get("window_size", 10),
            step=cfg_features.get("step", 1),
        )
        self.output_dir = cfg_pipeline["output_dir"]
        self.writer = DatasetWriter(output_dir=self.output_dir)
        self.output_format = cfg_inventory["output_format"]
        self.vectorizer_path = cfg_features.get(
            "vectorizer_path", f"{self.output_dir}/vectorizer.json"
        )
        self.cfg_models = self.config.get("models", {})
        # 학습 표본 상한 (0 = 전체). Inventory 집계에는 영향 없음.
        self.train_sample_size = cfg_pipeline.get("train_sample_size", 200000)
        self.store = LogStore(
            db_path=cfg_pipeline.get("db_path", f"{self.output_dir}/api_logs.db"),
            retain_days=cfg_pipeline.get("retain_days", 7),
        )

    # ── 메인 파이프라인 ────────────────────────────────────

    def run(self, inventory_only: bool = False):
        """파이프라인 실행.

        inventory_only=True 이면 0~1단계(정리 + Inventory 집계)만 수행하고
        Feature/딥러닝 학습(2~3단계)은 건너뛴다. 'Run Now'처럼 데이터만 빠르게
        갱신할 때 사용한다. 모델 재학습은 매일 자동 스케줄(full 실행)에서 수행한다.
        """
        logger.info("=== API Discovery pipeline started ===")
        start = time.time()

        # ── 0단계: 오래된 로그 정리 ──────────────────────────
        deleted = self.store.purge_old()
        logger.info(f"[0/3] DB cleanup: {deleted} rows deleted")

        if not self.store.has_any():
            logger.warning("No logs retained in DB - aborting pipeline")
            return self._empty_result()

        # ── 1단계: SQL 집계 → Inventory 구축 (전체) ─────────────
        # 수백만 행을 파이썬으로 순회하지 않고 SQLite GROUP BY로 집계한다.
        # (에러 요청 status>=400은 aggregate_inventory 내부에서 제외)
        self.inventory.load_aggregates(self.store.aggregate_inventory())
        filtered_inventory = self.inventory.get_inventory()
        self.inventory.save(self.output_dir, fmt=self.output_format)
        logger.info(
            f"[1/3] Inventory — {len(filtered_inventory)}개 Endpoint / "
            f"{sum(e['call_count'] for e in filtered_inventory)}회 호출"
        )

        # inventory_only: 여기서 종료 (Feature/학습 생략)
        if inventory_only:
            self._cleanup_old_files(keep=3)
            elapsed = round(time.time() - start, 2)
            logger.info(f"Elapsed: {elapsed}s (inventory only)")
            logger.info("=== Pipeline finished (inventory only) ===")
            return {
                "total_db_records": self.inventory.total_calls,
                "total_endpoints": self.inventory.total_endpoints,
                "total_calls": self.inventory.total_calls,
                "total_features": 0,
                "total_sequences": 0,
                "ae_summary": None,
                "lstm_summary": None,
                "elapsed_sec": elapsed,
                "inventory_only": True,
            }

        # ── 2단계: Feature Engineering (최근 표본만) ───────────
        # 학습은 전체가 아닌 최근 train_sample_size건의 성공 로그로 수행한다.
        # (Inventory는 위에서 이미 전체로 집계 완료)
        if self.train_sample_size and self.train_sample_size > 0:
            sample_rows = self.store.fetch_recent(self.train_sample_size)
        else:
            sample_rows = self.store.fetch_recent(0)  # 0 = 전체 (LIMIT -1)
        logger.info(f"[2/3] Loaded {len(sample_rows)} training samples")

        raw_features, vectors, sequences = [], [], []
        for row in sample_rows:
            log = ParsedLog.from_db_row(row)
            feat = self.extractor.extract(log)
            if feat:
                raw_features.append(feat)

        if raw_features:
            vectors = self.vectorizer.fit_transform(raw_features)
            self.vectorizer.save(self.vectorizer_path)
            self.writer.save_flat(vectors, raw_features)

            sequences = self.sequence_builder.build(raw_features)
            self.writer.save_sequences(sequences)

            self.writer.save_stats({
                "total_records": len(raw_features),
                "feature_dim": self.vectorizer.feature_dim,
                "feature_names": self.vectorizer.feature_names,
                "total_sequences": len(sequences),
                "window_size": self.sequence_builder.window_size,
                "unique_ips": len({f.remote_addr for f in raw_features}),
                "unique_endpoints": self.inventory.total_endpoints,
            })
            logger.info(
                f"[2/3] Feature Engineering — "
                f"{len(raw_features)}개 벡터, {len(sequences)}개 시퀀스"
            )
        else:
            logger.warning("[2/3] Feature engineering produced no data")

        # ── 3단계: 딥러닝 모델 학습 + 고급 이상 탐지 ─────────
        ae_summary, lstm_summary = None, None
        if vectors:
            logger.info("[3/4] Model training started")
            manager = ModelManager(
                config=self.cfg_models,
                feature_dim=self.vectorizer.feature_dim,
                seq_len=self.sequence_builder.window_size,
            )
            ae_meta = [
                {
                    "remote_addr": f.remote_addr,
                    "method": f.method,
                    "normalized_uri": f.normalized_uri,
                    "time_raw": f.time_raw,
                    "request_id": f.request_id,
                }
                for f in raw_features
            ]
            ae_summary = manager.train_autoencoder(vectors, meta=ae_meta)
            lstm_summary = manager.train_lstm(sequences)

            logger.info(
                f"[3/3] AutoEncoder — 이상 탐지: "
                f"{ae_summary.anomaly_count}/{ae_summary.total}건 "
                f"({ae_summary.anomaly_rate}%)"
            )
            if lstm_summary:
                logger.info(
                    f"[3/3] LSTM — 이상 시퀀스: "
                    f"{lstm_summary.anomaly_count}/{lstm_summary.total}건 "
                    f"({lstm_summary.anomaly_rate}%)"
                )

            # 엔드포인트 → 도메인 매핑 (최소 호출 수 통과한 것만)
            min_cc = self.inventory.min_call_count
            domain_map = {
                (e["method"], e["endpoint"]): e.get("domains", [])
                for e in self.inventory.get_inventory()
            }

            ml_endpoints = aggregate_ml_endpoints(
                ae_summary.results, domain_map=domain_map, min_call_count=min_cc
            )
            self._save_json(ml_endpoints, "ml_endpoint_anomaly.json")
            logger.info(f"[3/4] ML anomalous endpoints: {len(ml_endpoints)}")

            if lstm_summary:
                suspicious_ips = aggregate_suspicious_ips(lstm_summary.results)
                self._save_json(suspicious_ips, "suspicious_ips.json")
                logger.info(f"[3/4] Suspicious IPs: {len(suspicious_ips)}")

            time_anomalies = detect_time_anomalies(
                raw_features, domain_map=domain_map, min_call_count=min_cc
            )
            self._save_json(time_anomalies, "time_anomaly.json")
            logger.info(f"[3/4] Off-hour active endpoints: {len(time_anomalies)}")
        else:
            logger.warning("[3/4] No training data - skipping model training")

        self._cleanup_old_files(keep=3)

        elapsed = round(time.time() - start, 2)
        logger.info(f"Elapsed: {elapsed}s")
        logger.info("=== Pipeline finished ===")

        return {
            "total_db_records": self.inventory.total_calls,
            "total_endpoints": self.inventory.total_endpoints,
            "total_calls": self.inventory.total_calls,
            "total_features": len(raw_features),
            "total_sequences": len(sequences),
            "ae_summary": ae_summary,
            "lstm_summary": lstm_summary,
            "elapsed_sec": elapsed,
        }

    def _cleanup_old_files(self, keep: int = 3):
        patterns = [
            "api_inventory_*.json",
            "api_inventory_*.csv",
            "features_flat_*.csv",
            "features_sequences_*.json",
            "feature_stats_*.json",
        ]
        output = Path(self.output_dir)
        for pattern in patterns:
            files = sorted(output.glob(pattern))
            for old in files[:-keep]:
                old.unlink()
                logger.info(f"Deleted stale file: {old.name}")

    def _save_json(self, data, filename: str):
        path = Path(self.output_dir) / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _empty_result(self) -> dict:
        return {
            "total_db_records": 0,
            "total_endpoints": 0, "total_calls": 0,
            "total_features": 0, "total_sequences": 0,
            "ae_summary": None, "lstm_summary": None, "elapsed_sec": 0,
        }

import pytest
import torch
import json
from src.models.autoencoder import AutoEncoder
from src.models.lstm_model import LSTMAutoEncoder
from src.models.trainer import Trainer
from src.models.detector import AnomalyDetector

INPUT_DIM = 26
SEQ_LEN = 5
BATCH = 20


@pytest.fixture
def flat_data():
    torch.manual_seed(0)
    return torch.rand(BATCH, INPUT_DIM)


@pytest.fixture
def seq_data():
    torch.manual_seed(0)
    return torch.rand(BATCH, SEQ_LEN, INPUT_DIM)


# ── AutoEncoder ──────────────────────────────────────────

def test_ae_forward_shape(flat_data):
    model = AutoEncoder(input_dim=INPUT_DIM, hidden_dims=[16, 8])
    out = model(flat_data)
    assert out.shape == flat_data.shape


def test_ae_output_range(flat_data):
    model = AutoEncoder(input_dim=INPUT_DIM, hidden_dims=[16, 8])
    out = model(flat_data)
    assert out.min() >= 0.0 and out.max() <= 1.0


def test_ae_reconstruction_error_shape(flat_data):
    model = AutoEncoder(input_dim=INPUT_DIM, hidden_dims=[16, 8])
    errors = model.reconstruction_error(flat_data)
    assert errors.shape == (BATCH,)


# ── LSTMAutoEncoder ──────────────────────────────────────

def test_lstm_forward_shape(seq_data):
    model = LSTMAutoEncoder(input_dim=INPUT_DIM, hidden_dim=16, seq_len=SEQ_LEN)
    out = model(seq_data)
    assert out.shape == seq_data.shape


def test_lstm_reconstruction_error_shape(seq_data):
    model = LSTMAutoEncoder(input_dim=INPUT_DIM, hidden_dim=16, seq_len=SEQ_LEN)
    errors = model.reconstruction_error(seq_data)
    assert errors.shape == (BATCH,)


# ── Trainer ──────────────────────────────────────────────

def test_trainer_ae_loss_decreases(flat_data):
    model = AutoEncoder(input_dim=INPUT_DIM, hidden_dims=[16, 8])
    trainer = Trainer(model, lr=1e-2, batch_size=10, max_epochs=20, patience=20)
    history = trainer.train(flat_data)
    assert history[-1]["train_loss"] < history[0]["train_loss"]


def test_trainer_early_stopping(flat_data):
    model = AutoEncoder(input_dim=INPUT_DIM, hidden_dims=[16, 8])
    trainer = Trainer(model, lr=1e-2, batch_size=10, max_epochs=200, patience=3)
    history = trainer.train(flat_data)
    assert len(history) < 200  # patience로 조기 종료


# ── AnomalyDetector ───────────────────────────────────────

def test_detector_threshold_set(flat_data):
    model = AutoEncoder(input_dim=INPUT_DIM, hidden_dims=[16, 8])
    detector = AnomalyDetector(model, threshold_percentile=90.0)
    detector.fit_threshold(flat_data)
    assert detector.threshold is not None and detector.threshold > 0


def test_detector_anomaly_rate(flat_data):
    model = AutoEncoder(input_dim=INPUT_DIM, hidden_dims=[16, 8])
    detector = AnomalyDetector(model, threshold_percentile=90.0)
    detector.fit_threshold(flat_data)
    summary = detector.detect(flat_data)
    # 90th percentile 임계값이면 약 10%가 이상으로 판정
    assert summary.total == BATCH
    assert 0 < summary.anomaly_count <= BATCH


def test_detector_save_load_threshold(flat_data, tmp_path):
    model = AutoEncoder(input_dim=INPUT_DIM, hidden_dims=[16, 8])
    detector = AnomalyDetector(model, threshold_percentile=95.0)
    detector.fit_threshold(flat_data)
    path = str(tmp_path / "threshold.json")
    detector.save_threshold(path)

    detector2 = AnomalyDetector(model, threshold_percentile=95.0)
    detector2.load_threshold(path)
    assert abs(detector.threshold - detector2.threshold) < 1e-9

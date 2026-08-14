"""
AutoEncoder / LSTMAutoEncoder 공통 학습 루프.
Early Stopping + 학습 곡선 저장 포함.
"""

import json
import logging
from pathlib import Path
from typing import List, Optional, Tuple

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset, random_split

logger = logging.getLogger(__name__)


class EarlyStopping:
    def __init__(self, patience: int = 10, min_delta: float = 1e-5):
        self.patience = patience
        self.min_delta = min_delta
        self.best_loss = float("inf")
        self.counter = 0

    def step(self, val_loss: float) -> bool:
        """True 반환 시 학습 중단."""
        if val_loss < self.best_loss - self.min_delta:
            self.best_loss = val_loss
            self.counter = 0
        else:
            self.counter += 1
        return self.counter >= self.patience


class Trainer:
    def __init__(
        self,
        model: nn.Module,
        lr: float = 1e-3,
        batch_size: int = 64,
        max_epochs: int = 100,
        val_ratio: float = 0.1,
        patience: int = 10,
        device: Optional[str] = None,
    ):
        self.model = model
        self.batch_size = batch_size
        self.max_epochs = max_epochs
        self.val_ratio = val_ratio
        self.device = torch.device(
            device if device else ("cuda" if torch.cuda.is_available() else "cpu")
        )
        self.model.to(self.device)
        self.optimizer = torch.optim.Adam(model.parameters(), lr=lr)
        self.criterion = nn.MSELoss()
        self.early_stopping = EarlyStopping(patience=patience)
        self.history: List[dict] = []

    def _make_loaders(self, tensor: torch.Tensor) -> Tuple[DataLoader, DataLoader]:
        dataset = TensorDataset(tensor)
        val_size = max(1, int(len(dataset) * self.val_ratio))
        train_size = len(dataset) - val_size
        train_ds, val_ds = random_split(dataset, [train_size, val_size])
        train_loader = DataLoader(train_ds, batch_size=self.batch_size, shuffle=True)
        val_loader = DataLoader(val_ds, batch_size=self.batch_size)
        return train_loader, val_loader

    def train(self, data: torch.Tensor) -> List[dict]:
        """
        data: (N, feature_dim) 또는 (N, seq_len, feature_dim)
        반환: epoch별 loss history
        """
        train_loader, val_loader = self._make_loaders(data)
        logger.info(f"Training started - device: {self.device}, "
                    f"train: {len(train_loader.dataset)}, "
                    f"val: {len(val_loader.dataset)}")

        for epoch in range(1, self.max_epochs + 1):
            train_loss = self._train_epoch(train_loader)
            val_loss = self._eval_epoch(val_loader)
            self.history.append({"epoch": epoch, "train_loss": train_loss, "val_loss": val_loss})

            if epoch % 10 == 0 or epoch == 1:
                logger.info(f"Epoch {epoch:>4}/{self.max_epochs} | "
                            f"train_loss: {train_loss:.6f} | val_loss: {val_loss:.6f}")

            if self.early_stopping.step(val_loss):
                logger.info(f"Early stopping at epoch {epoch} (best val_loss: {self.early_stopping.best_loss:.6f})")
                break

        return self.history

    def _train_epoch(self, loader: DataLoader) -> float:
        self.model.train()
        total = 0.0
        for (batch,) in loader:
            batch = batch.to(self.device)
            self.optimizer.zero_grad()
            recon = self.model(batch)
            loss = self.criterion(recon, batch)
            loss.backward()
            self.optimizer.step()
            total += loss.item() * len(batch)
        return total / len(loader.dataset)

    def _eval_epoch(self, loader: DataLoader) -> float:
        self.model.eval()
        total = 0.0
        with torch.no_grad():
            for (batch,) in loader:
                batch = batch.to(self.device)
                recon = self.model(batch)
                loss = self.criterion(recon, batch)
                total += loss.item() * len(batch)
        return total / len(loader.dataset)

    def save_history(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.history, f, indent=2)
        logger.info(f"Training curve saved: {path}")

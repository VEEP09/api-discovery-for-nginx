"""
AutoEncoder 기반 이상 탐지.
정상 API 호출 패턴을 학습하고 재구성 오차(Reconstruction Error)로 이상 점수 산출.
비지도 학습 — 라벨 불필요.
"""

import torch
import torch.nn as nn
from typing import List


class AutoEncoder(nn.Module):
    def __init__(self, input_dim: int, hidden_dims: List[int] = None):
        """
        input_dim: feature 벡터 차원 수 (vectorizer.feature_dim)
        hidden_dims: 인코더 레이어 크기 (디코더는 역순 자동 생성)
        """
        super().__init__()
        if hidden_dims is None:
            hidden_dims = [16, 8]

        # Encoder
        encoder_layers = []
        prev_dim = input_dim
        for dim in hidden_dims:
            encoder_layers += [nn.Linear(prev_dim, dim), nn.ReLU()]
            prev_dim = dim
        self.encoder = nn.Sequential(*encoder_layers)

        # Decoder (역순, 마지막은 Sigmoid로 [0,1] 범위 복원)
        decoder_layers = []
        for dim in reversed(hidden_dims[:-1]):
            decoder_layers += [nn.Linear(prev_dim, dim), nn.ReLU()]
            prev_dim = dim
        decoder_layers.append(nn.Linear(prev_dim, input_dim))
        decoder_layers.append(nn.Sigmoid())
        self.decoder = nn.Sequential(*decoder_layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.decoder(self.encoder(x))

    def reconstruction_error(self, x: torch.Tensor) -> torch.Tensor:
        """샘플별 MSE 반환 (shape: [batch_size])."""
        recon = self.forward(x)
        return ((recon - x) ** 2).mean(dim=1)

"""
LSTM AutoEncoder 기반 시계열 이상 탐지.
API 호출 시퀀스를 인코딩 → 복원하며 정상 흐름을 학습.
반복 호출, 스캐닝, 비정상 시퀀스 탐지에 사용.
"""

import torch
import torch.nn as nn


class LSTMEncoder(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int, num_layers: int):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
        )

    def forward(self, x: torch.Tensor):
        # x: (batch, seq_len, input_dim)
        _, (hidden, _) = self.lstm(x)
        # hidden: (num_layers, batch, hidden_dim) → 마지막 레이어만 사용
        return hidden[-1]  # (batch, hidden_dim)


class LSTMDecoder(nn.Module):
    def __init__(self, hidden_dim: int, output_dim: int, seq_len: int, num_layers: int):
        super().__init__()
        self.seq_len = seq_len
        self.lstm = nn.LSTM(
            input_size=hidden_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
        )
        self.output_layer = nn.Linear(hidden_dim, output_dim)

    def forward(self, z: torch.Tensor) -> torch.Tensor:
        # z: (batch, hidden_dim) → seq_len번 반복하여 디코딩
        z_repeated = z.unsqueeze(1).repeat(1, self.seq_len, 1)
        out, _ = self.lstm(z_repeated)
        return self.output_layer(out)  # (batch, seq_len, output_dim)


class LSTMAutoEncoder(nn.Module):
    def __init__(
        self,
        input_dim: int,
        hidden_dim: int = 32,
        seq_len: int = 10,
        num_layers: int = 1,
    ):
        super().__init__()
        self.encoder = LSTMEncoder(input_dim, hidden_dim, num_layers)
        self.decoder = LSTMDecoder(hidden_dim, input_dim, seq_len, num_layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z = self.encoder(x)
        return self.decoder(z)

    def reconstruction_error(self, x: torch.Tensor) -> torch.Tensor:
        """시퀀스 전체 평균 MSE 반환 (shape: [batch_size])."""
        recon = self.forward(x)
        return ((recon - x) ** 2).mean(dim=(1, 2))

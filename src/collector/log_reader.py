"""
로그 파일을 읽어 raw 줄 단위로 yield하는 모듈.
배치 처리와 증분 읽기(tail -f 방식)를 모두 지원.
"""

import os
import time
from pathlib import Path
from typing import Iterator, List


class LogReader:
    def __init__(self, log_path: str, batch_size: int = 10000):
        self.log_path = Path(log_path)
        self.batch_size = batch_size

    def read_batch(self) -> Iterator[List[str]]:
        """파일 전체를 batch_size 단위로 읽어 yield."""
        if not self.log_path.exists():
            raise FileNotFoundError(f"로그 파일을 찾을 수 없습니다: {self.log_path}")

        with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
            batch = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                batch.append(line)
                if len(batch) >= self.batch_size:
                    yield batch
                    batch = []
            if batch:
                yield batch

    def read_incremental(self, poll_interval: float = 1.0) -> Iterator[str]:
        """파일 끝에서부터 새 줄이 추가될 때마다 yield (tail -f 방식)."""
        if not self.log_path.exists():
            raise FileNotFoundError(f"로그 파일을 찾을 수 없습니다: {self.log_path}")

        with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, os.SEEK_END)
            while True:
                line = f.readline()
                if line:
                    line = line.strip()
                    if line:
                        yield line
                else:
                    time.sleep(poll_interval)

    def read_all(self) -> Iterator[str]:
        """파일 전체를 줄 단위로 yield."""
        for batch in self.read_batch():
            yield from batch

    @property
    def file_size(self) -> int:
        return self.log_path.stat().st_size if self.log_path.exists() else 0

    @property
    def line_count(self) -> int:
        if not self.log_path.exists():
            return 0
        with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)

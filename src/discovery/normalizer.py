"""
URI Path를 정규화하여 API Endpoint 템플릿을 추출.
예: /api/v1/users/1042 → /api/v1/users/{id}

설정 파일의 normalizers 순서대로 적용되므로
uuid → date → numeric_id 순서를 유지해야 오탐이 없음.
"""

import re
from dataclasses import dataclass
from typing import List


@dataclass
class NormalizerRule:
    name: str
    pattern: re.Pattern
    placeholder: str


class URINormalizer:
    def __init__(
        self,
        rules: List[dict],
        exclude_prefixes: List[str] = None,
        exclude_extensions: List[str] = None,
    ):
        self.rules: List[NormalizerRule] = [
            NormalizerRule(
                name=r["name"],
                pattern=re.compile(r["pattern"], re.IGNORECASE),
                placeholder=r["placeholder"],
            )
            for r in rules
        ]
        self.exclude_prefixes = [p.rstrip("/") for p in (exclude_prefixes or [])]
        self.exclude_extensions = [e.lower() for e in (exclude_extensions or [])]

    def is_excluded(self, uri: str) -> bool:
        path = uri.split("?")[0]
        if any(path.startswith(prefix) for prefix in self.exclude_prefixes):
            return True
        if self.exclude_extensions:
            lower = path.lower()
            if any(lower.endswith(ext) for ext in self.exclude_extensions):
                return True
        return False

    def normalize(self, uri: str) -> str:
        """URI를 segment 단위로 분리하여 각 segment에 정규화 규칙 적용."""
        if self.is_excluded(uri):
            return uri

        # query string이 섞여 들어오는 경우 제거 (uri 필드는 원래 없어야 하지만 방어)
        uri = uri.split("?")[0]

        segments = uri.split("/")
        normalized = []
        for seg in segments:
            normalized.append(self._normalize_segment(seg))
        return "/".join(normalized)

    def _normalize_segment(self, segment: str) -> str:
        if not segment:
            return segment
        for rule in self.rules:
            # 세그먼트 전체가 패턴과 일치하는 경우만 치환 (부분 매치 방지)
            if rule.pattern.fullmatch(segment):
                return rule.placeholder
        return segment

    def extract_version(self, uri: str) -> str:
        """URI에서 버전 정보 추출. /v1/, /v2/ 등."""
        match = re.search(r"/(v\d+(?:\.\d+)?)/", uri)
        return match.group(1) if match else ""

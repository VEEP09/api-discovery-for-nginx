"""
OpenAPI 2.0(Swagger) / 3.0 스펙 파일 파싱.
YAML / JSON 모두 지원. 정의된 (method, path) 집합을 반환.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Set, Tuple

import yaml


@dataclass
class OpenAPIEndpoint:
    method: str
    path: str
    operation_id: str = ""
    summary: str = ""
    tags: List[str] = field(default_factory=list)

    @property
    def match_key(self) -> str:
        """path parameter 이름을 무시하고 구조만 비교하는 키."""
        normalized = re.sub(r"\{[^}]+\}", "{}", self.path)
        return f"{self.method.upper()}:{normalized}"


@dataclass
class OpenAPISpec:
    title: str
    version: str
    openapi_version: str         # "2.x" or "3.x"
    base_path: str               # Swagger 2.0 basePath (3.0은 "")
    endpoints: List[OpenAPIEndpoint] = field(default_factory=list)
    raw_path: str = ""

    @property
    def endpoint_count(self) -> int:
        return len(self.endpoints)

    @property
    def match_keys(self) -> Set[str]:
        return {e.match_key for e in self.endpoints}


HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}


def parse_spec(file_path: str) -> OpenAPISpec:
    path = Path(file_path)
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)   # JSON도 유효한 YAML

    if "swagger" in raw:
        return _parse_v2(raw, str(path))
    elif "openapi" in raw:
        return _parse_v3(raw, str(path))
    else:
        raise ValueError("OpenAPI 2.0(swagger) 또는 3.0(openapi) 키가 없습니다.")


def _parse_v2(raw: dict, file_path: str) -> OpenAPISpec:
    info = raw.get("info", {})
    base_path = raw.get("basePath", "").rstrip("/")
    paths = raw.get("paths", {})

    endpoints = _extract_endpoints(paths, base_path)
    return OpenAPISpec(
        title=info.get("title", "Unknown"),
        version=info.get("version", ""),
        openapi_version=f"2.{raw.get('swagger', '0')}",
        base_path=base_path,
        endpoints=endpoints,
        raw_path=file_path,
    )


def _parse_v3(raw: dict, file_path: str) -> OpenAPISpec:
    info = raw.get("info", {})
    paths = raw.get("paths", {})

    endpoints = _extract_endpoints(paths, "")
    return OpenAPISpec(
        title=info.get("title", "Unknown"),
        version=info.get("version", ""),
        openapi_version=raw.get("openapi", "3.0"),
        base_path="",
        endpoints=endpoints,
        raw_path=file_path,
    )


def _extract_endpoints(paths: dict, base_path: str) -> List[OpenAPIEndpoint]:
    endpoints = []
    for path, path_item in (paths or {}).items():
        if not isinstance(path_item, dict):
            continue
        full_path = base_path + path
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                continue
            endpoints.append(OpenAPIEndpoint(
                method=method.upper(),
                path=full_path,
                operation_id=operation.get("operationId", ""),
                summary=operation.get("summary", ""),
                tags=operation.get("tags", []),
            ))
    return endpoints

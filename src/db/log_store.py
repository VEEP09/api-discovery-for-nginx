"""
SQLite 기반 로그 저장소.
- 증분 읽기: file cursor (offset + inode) 로 중복 삽입 방지
- 자동 정리: retain_days 초과분 삭제
"""

import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple
from zoneinfo import ZoneInfo

_KST = ZoneInfo("Asia/Seoul")

logger = logging.getLogger(__name__)

# 레이턴시 백분위 근사용 누적 히스토그램 버킷 경계(초). aggregate_inventory가
# 같은 스캔에서 각 경계 이하 요청 수(누적)를 세고, _pctl_from_hist가 선형 보간한다.
_LAT_BUCKETS = [0.0, 0.001, 0.002, 0.003, 0.005, 0.0075,
                0.01, 0.015, 0.02, 0.03, 0.05, 0.075,
                0.1, 0.15, 0.2, 0.3, 0.5, 0.75,
                1.0, 1.5, 2.0, 3.0, 5.0, 7.5, 10.0, 15.0, 30.0]


def _pctl_from_hist(cum, rt_count: int, p: float) -> float:
    """누적 히스토그램에서 p 백분위를 선형 보간해 근사(초 단위).

    cum: [(경계초, 경계이하_누적카운트), ...] 오름차순. rt_count: 전체(비 NULL) 수.
    같은 cum에서 뽑으므로 p50<=p95<=p99 순서가 항상 보장된다. 최상단 버킷을
    넘는 값은 최상단 경계로 캡한다.
    """
    if rt_count <= 0:
        return 0.0
    target = p * rt_count
    prev_le = 0.0
    prev_c = 0
    for le, c in cum:
        if c >= target:
            if c == prev_c:
                return round(le, 4)
            frac = (target - prev_c) / (c - prev_c)
            return round(prev_le + frac * (le - prev_le), 4)
        prev_le, prev_c = le, c
    return round(_LAT_BUCKETS[-1], 4)

_DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS api_logs (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    time                   TEXT    NOT NULL,
    remote_addr            TEXT    NOT NULL,
    method                 TEXT    NOT NULL,
    uri                    TEXT    NOT NULL,
    normalized_uri         TEXT    NOT NULL,
    api_version            TEXT,
    query_string           TEXT,
    status                 INTEGER NOT NULL,
    body_bytes_sent        INTEGER,
    request_length         INTEGER,
    request_time           REAL,
    upstream_response_time REAL,
    http_user_agent        TEXT,
    http_authorization     TEXT,
    has_auth               INTEGER,
    auth_type              TEXT,
    host                   TEXT,
    request_id             TEXT,
    inserted_at            TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ins ON api_logs(inserted_at);
CREATE INDEX IF NOT EXISTS idx_time ON api_logs(time);
-- inventory 탭 sample_request 조회용 (조합별 대표 1건 선별)
CREATE INDEX IF NOT EXISTS idx_sample ON api_logs(method, normalized_uri, host, status, time);

CREATE TABLE IF NOT EXISTS log_cursor (
    file_path   TEXT    PRIMARY KEY,
    last_offset INTEGER NOT NULL DEFAULT 0,
    inode       INTEGER NOT NULL DEFAULT 0
);
"""


class LogStore:
    def __init__(self, db_path: str, retain_days: int = 7):
        self.db_path = db_path
        self.retain_days = retain_days
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_DDL)
            self._migrate(conn)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Migration ───────────────────────────────────────────

    def _migrate(self, conn):
        cols = {row[1] for row in conn.execute("PRAGMA table_info(api_logs)")}
        if "server_name" in cols and "host" not in cols:
            conn.execute("ALTER TABLE api_logs RENAME COLUMN server_name TO host")
            logger.info("DB migration: server_name -> host")

    # ── Cursor ──────────────────────────────────────────────

    def get_cursor(self, file_path: str) -> Tuple[int, int]:
        """저장된 (last_offset, inode). 없으면 (0, 0)."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT last_offset, inode FROM log_cursor WHERE file_path=?",
                (file_path,),
            ).fetchone()
        return (row["last_offset"], row["inode"]) if row else (0, 0)

    def set_cursor(self, file_path: str, last_offset: int, inode: int):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO log_cursor(file_path, last_offset, inode) VALUES(?,?,?)",
                (file_path, last_offset, inode),
            )

    # ── Insert ──────────────────────────────────────────────

    def insert_batch(self, rows: list) -> int:
        if not rows:
            return 0
        with self._conn() as conn:
            conn.executemany(
                """INSERT INTO api_logs
                   (time, remote_addr, method, uri, normalized_uri, api_version,
                    query_string, status, body_bytes_sent, request_length,
                    request_time, upstream_response_time, http_user_agent,
                    http_authorization, has_auth, auth_type, host,
                    request_id, inserted_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
        return len(rows)

    # ── Purge ───────────────────────────────────────────────

    def purge_old(self) -> int:
        cutoff = (datetime.now(_KST) - timedelta(days=self.retain_days)).isoformat(
            timespec="seconds"
        )
        with self._conn() as conn:
            n = conn.execute(
                "DELETE FROM api_logs WHERE time < ?", (cutoff,)
            ).rowcount
        if n:
            logger.info(f"DB cleanup: {n} rows deleted (older than {self.retain_days} days by request time)")
        return n

    # ── Fetch ───────────────────────────────────────────────

    def fetch_all(self) -> List[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM api_logs ORDER BY time ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def fetch_recent(self, limit: int, max_status: int = 400) -> List[dict]:
        """최근 성공 로그 limit건을 시간 오름차순으로 반환 (학습 표본용).

        DL 이상탐지 학습은 전체가 아니라 대표 표본으로 충분하다.
        id 역순으로 최근 limit건을 고른 뒤, 시퀀스 빌더가 시간순을 기대하므로
        다시 시간 오름차순으로 정렬해 돌려준다. limit<=0이면 전체를 반환한다.
        """
        if limit <= 0:
            limit = -1  # SQLite에서 LIMIT -1 은 무제한
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM ("
                "  SELECT * FROM api_logs WHERE status < ? "
                "  ORDER BY id DESC LIMIT ?"
                ") ORDER BY time ASC",
                (max_status, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def has_any(self) -> bool:
        """행이 하나라도 있는지 (COUNT 없이 저비용 확인)."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT 1 FROM api_logs LIMIT 1"
            ).fetchone() is not None

    def aggregate_inventory(self, max_status: int = 400) -> List[dict]:
        """(method, normalized_uri)별 Inventory 집계를 SQL로 계산해 반환한다.

        기존에는 수백만 행을 파이썬으로 순회하며 집계해 수 분이 걸렸다.
        집계 내용(카운트·min/max·distinct·평균)은 전부 SQL로 표현 가능하므로
        SQLite가 C 레벨에서 처리하도록 옮겼다.
        반환 dict는 EndpointStat.to_dict()와 동일한 스키마를 따른다.
        에러(status >= max_status) 요청은 Inventory에서 제외한다(기존 정책).

        레이턴시 백분위(p50/p95/p99)도 이 집계에 함께 담는다. api_logs 풀스캔은
        IO-bound라 별도 스캔이 매우 비싸므로(백만 건 규모에서 수백 초), 정렬이
        필요한 정확 백분위 대신 고정 버킷 누적 히스토그램(_LAT_BUCKETS)을 같은
        GROUP BY 스캔에서 SUM(CASE)로 세고, 파이썬에서 선형 보간해 근사한다
        (Prometheus histogram_quantile과 동일한 방식, 추가 스캔 0회).
        """
        # 누적("<=") 히스토그램 컬럼. request_time NULL은 자연히 제외된다.
        bucket_cols = ",\n                ".join(
            f"SUM(CASE WHEN request_time <= {le} THEN 1 ELSE 0 END) AS le_{i}"
            for i, le in enumerate(_LAT_BUCKETS)
        )
        sql = f"""
            SELECT
                method,
                normalized_uri                                        AS endpoint,
                COUNT(*)                                              AS call_count,
                SUM(CASE WHEN status BETWEEN 200 AND 299 THEN 1 ELSE 0 END) AS status_2xx,
                SUM(CASE WHEN status BETWEEN 300 AND 399 THEN 1 ELSE 0 END) AS status_3xx,
                SUM(CASE WHEN status BETWEEN 400 AND 499 THEN 1 ELSE 0 END) AS status_4xx,
                SUM(CASE WHEN status BETWEEN 500 AND 599 THEN 1 ELSE 0 END) AS status_5xx,
                ROUND(AVG(COALESCE(request_time, 0)), 4)             AS avg_response_time,
                SUM(CASE WHEN request_time IS NOT NULL THEN 1 ELSE 0 END) AS rt_count,
                {bucket_cols},
                MAX(COALESCE(has_auth, 0))                           AS has_auth,
                COUNT(DISTINCT remote_addr)                          AS unique_ip_count,
                MIN(time)                                            AS first_seen,
                MAX(time)                                            AS last_seen,
                GROUP_CONCAT(DISTINCT NULLIF(host, ''))              AS domains_csv,
                GROUP_CONCAT(DISTINCT CASE WHEN has_auth = 1 THEN NULLIF(auth_type, '') END) AS auth_csv,
                MAX(COALESCE(api_version, ''))                       AS api_version
            FROM api_logs NOT INDEXED
            WHERE status < ?
            GROUP BY method, normalized_uri
        """
        # NOT INDEXED: idx_sample를 타면 인덱스 순회 + 행별 랜덤 조회로
        # 240만 건 기준 ~210초가 걸린다. 전체 순차 스캔으로 강제하면 크게 단축된다.
        # 히스토그램 SUM(CASE) 컬럼은 CPU 비용만 더할 뿐 스캔은 여전히 1회다.
        result: List[dict] = []
        with self._conn() as conn:
            for r in conn.execute(sql, (max_status,)):
                cc = r["call_count"] or 0
                domains = sorted(d for d in (r["domains_csv"] or "").split(",") if d)
                auth_types = [a for a in (r["auth_csv"] or "").split(",") if a]
                rt_count = r["rt_count"] or 0
                cum = [(le, r[f"le_{i}"] or 0) for i, le in enumerate(_LAT_BUCKETS)]
                result.append({
                    "method": r["method"],
                    "endpoint": r["endpoint"],
                    "api_version": r["api_version"] or "",
                    "call_count": cc,
                    "status_2xx": r["status_2xx"] or 0,
                    "status_3xx": r["status_3xx"] or 0,
                    "status_4xx": r["status_4xx"] or 0,
                    "status_5xx": r["status_5xx"] or 0,
                    "error_rate": round(((r["status_4xx"] or 0) + (r["status_5xx"] or 0)) / cc * 100, 2) if cc else 0,
                    "avg_response_time": r["avg_response_time"] or 0.0,
                    "p50_response_time": _pctl_from_hist(cum, rt_count, 0.50),
                    "p95_response_time": _pctl_from_hist(cum, rt_count, 0.95),
                    "p99_response_time": _pctl_from_hist(cum, rt_count, 0.99),
                    "has_auth": bool(r["has_auth"]),
                    "auth_types": auth_types,
                    "unique_ip_count": r["unique_ip_count"] or 0,
                    "domains": domains,
                    "first_seen": r["first_seen"] or "",
                    "last_seen": r["last_seen"] or "",
                })
        return result

    def fetch_page(
        self,
        page: int = 1,
        per_page: int = 100,
        method: str = "",
        uri: str = "",
        sort: str = "time",
        order: str = "desc",
        date_from: str = "",
        date_to: str = "",
    ) -> Tuple[List[dict], int]:
        """페이지네이션 + 필터링된 로그 반환. (rows, total_count) 튜플."""
        allowed_sort = {"time", "method", "uri", "status", "remote_addr", "request_time"}
        sort_col = sort if sort in allowed_sort else "time"
        sort_dir = "DESC" if order.lower() == "desc" else "ASC"

        conditions, params = [], []
        if method:
            conditions.append("UPPER(method) = UPPER(?)")
            params.append(method)
        if uri:
            conditions.append("(uri LIKE ? OR normalized_uri LIKE ?)")
            params.extend([f"%{uri}%", f"%{uri}%"])
        if date_from:
            conditions.append("time >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("time <= ?")
            params.append(date_to)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        with self._conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM api_logs {where}", params
            ).fetchone()[0]

            rows = conn.execute(
                f"SELECT * FROM api_logs {where} "
                f"ORDER BY {sort_col} {sort_dir} "
                f"LIMIT ? OFFSET ?",
                params + [per_page, (page - 1) * per_page],
            ).fetchall()

        return [dict(r) for r in rows], total

    @property
    def total_records(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM api_logs").fetchone()[0]

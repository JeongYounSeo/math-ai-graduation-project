"""problem_regions 테이블에 좌표 승격 컬럼 7종을 추가하는 마이그레이션.

배경(설계 DESIGN_region_coord_validation.md §2.1):
- SQLAlchemy ``create_all()`` 은 **기존 테이블에 컬럼을 추가하지 않는다**.
- 따라서 보존 데이터가 있는 DB(운영/기존 개발 DB)에는 이 스크립트로
  ``ALTER TABLE problem_regions ADD COLUMN ...`` 을 수행한다.

추가 컬럼: x1, y1, x2, y2, page_width, page_height (FLOAT),
parent_region_id (INTEGER, plain int — DB-level ForeignKey 미사용 관례).

idempotent: ``PRAGMA table_info`` 로 기존 컬럼을 확인해 이미 존재하면 건너뛴다.

사용법:
    python scripts/migrate_add_region_coords.py

대상 DB:
    DATABASE_URL 환경변수가 있으면 우선 사용(sqlite URL만 지원).
    없으면 기본 ``sqlite:///./math_problem_engine.db``.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

_TABLE = "problem_regions"

# (컬럼명, SQLite 타입) — ALTER TABLE ADD COLUMN 용.
_NEW_COLUMNS: list[tuple[str, str]] = [
    ("x1", "FLOAT"),
    ("y1", "FLOAT"),
    ("x2", "FLOAT"),
    ("y2", "FLOAT"),
    ("page_width", "FLOAT"),
    ("page_height", "FLOAT"),
    ("parent_region_id", "INTEGER"),
]


def _resolve_sqlite_path() -> str:
    """DATABASE_URL(우선) 또는 기본값에서 sqlite 파일 경로를 뽑아낸다."""
    url = os.getenv("DATABASE_URL", "sqlite:///./math_problem_engine.db")
    if not url.startswith("sqlite"):
        raise SystemExit(
            f"이 마이그레이션은 sqlite DB만 지원합니다. DATABASE_URL={url!r}"
        )
    # sqlite:///relative/path  또는  sqlite:////absolute/path
    # 접두사 'sqlite://' 이후가 경로. 인메모리(sqlite://)는 마이그레이션 대상 아님.
    path_part = url[len("sqlite://"):]
    if path_part in ("", "/"):
        raise SystemExit("인메모리 sqlite DB는 마이그레이션 대상이 아닙니다.")
    # 'sqlite:///./foo.db' -> '/./foo.db' -> './foo.db'
    if path_part.startswith("/"):
        path_part = path_part[1:]
    return path_part


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone() is not None


def migrate(db_path: str) -> int:
    """마이그레이션 실행. 추가한 컬럼 수를 반환한다."""
    print(f"[migrate] 대상 DB: {db_path}")
    if not Path(db_path).exists():
        print(
            f"[migrate] DB 파일이 없습니다: {db_path}\n"
            f"          앱을 한 번 실행해 테이블을 생성했는지 확인하세요."
        )
        return 0

    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, _TABLE):
            print(f"[migrate] '{_TABLE}' 테이블이 없어 건너뜁니다.")
            return 0

        existing = _existing_columns(conn, _TABLE)
        added = 0
        for name, sql_type in _NEW_COLUMNS:
            if name in existing:
                print(f"[migrate] 컬럼 이미 존재 → 건너뜀: {name}")
                continue
            conn.execute(f"ALTER TABLE {_TABLE} ADD COLUMN {name} {sql_type}")
            print(f"[migrate] 컬럼 추가: {name} {sql_type}")
            added += 1
        conn.commit()
        print(f"[migrate] 완료. 추가한 컬럼 수: {added}")
        return added
    finally:
        conn.close()


def main() -> int:
    db_path = _resolve_sqlite_path()
    migrate(db_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

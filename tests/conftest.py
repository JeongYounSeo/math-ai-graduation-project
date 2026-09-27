"""공용 테스트 인프라: 네트워크 차단 가드와 격리된 SQLite 세션 픽스처.

- `_block_network`(autouse): 루프백이 아닌 주소로의 실제 아웃바운드 소켓 연결을
  차단해, 미목킹 네트워크 호출이 발생하면 테스트가 명확한 오류로 실패하게 한다
  (Req 15.2, 15.3, 15.5). FastAPI TestClient는 ASGI 앱을 인프로세스로 호출하므로
  실제 소켓을 열지 않아 이 가드에 영향받지 않는다.
- `db_session`: 신규 스키마 테이블이 모두 생성된 격리 SQLite 세션을 제공한다.
"""

import socket

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# 루프백(로컬) 주소는 허용한다. FastAPI TestClient는 실제 소켓을 열지 않지만,
# 로컬 sqlite/기타 로컬 연결이 있어도 가드가 방해하지 않도록 한다.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", ""})


def _host_from_address(address):
    """소켓 주소 인자에서 호스트 부분을 최선으로 추출한다."""
    if isinstance(address, (tuple, list)) and address:
        return address[0]
    return address


def _is_loopback(host) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except Exception:  # noqa: BLE001
            return False
    return host in _LOOPBACK_HOSTS


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    """루프백이 아닌 실제 네트워크 호출을 차단하는 autouse 가드.

    socket.socket.connect / socket.create_connection 을 패치해, 루프백이 아닌
    주소로의 연결 시도 시 RuntimeError를 발생시킨다. 루프백 대상은 원본 동작을
    그대로 위임한다. teardown 시 monkeypatch가 원본을 복원한다.
    """
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def guarded_connect(self, address, *args, **kwargs):
        host = _host_from_address(address)
        if not _is_loopback(host):
            raise RuntimeError(
                f"Unmocked network call detected (connect -> {host!r})"
            )
        return original_connect(self, address, *args, **kwargs)

    def guarded_create_connection(address, *args, **kwargs):
        host = _host_from_address(address)
        if not _is_loopback(host):
            raise RuntimeError(
                f"Unmocked network call detected (create_connection -> {host!r})"
            )
        return original_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect, raising=True)
    monkeypatch.setattr(
        socket, "create_connection", guarded_create_connection, raising=True
    )
    yield
    # monkeypatch가 teardown에서 원본을 자동 복원한다.


@pytest.fixture
def db_session():
    """신규 스키마 테이블이 모두 생성된 격리 SQLite 세션을 제공한다.

    인메모리 SQLite + StaticPool 로 단일 연결을 공유하며, 연결마다
    `PRAGMA foreign_keys=ON` 을 실행해 FK 무결성을 강제한다. teardown 시
    세션을 닫고 엔진을 dispose 한다.
    """
    # 모델을 import 해 Base.metadata에 등록한다(순서 무관, FK 대상 포함).
    from app.core.db_base import Base
    import app.models.source_pdf  # noqa: F401
    import app.models.passage  # noqa: F401
    import app.models.problem  # noqa: F401
    import app.models.problem_region  # noqa: F401
    import app.models.problem_region_item  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)

    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()

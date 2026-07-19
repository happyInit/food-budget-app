"""chat_message 읽기 — 대화 분석/개인화/의도학습의 공통 입력(read-only 스냅샷).

랭킹 extract.py와 동일 정책: PG는 읽기 1회, 처리는 오프라인. chat 서비스는 read-only라
쓰기(chat_message insert)는 백엔드(#127) 몫 — 여기선 **읽기만** 한다.

⚠️ chat.chat_message가 라이브 DB에 미마이그레이션이면 명확히 안내하고 skip(#131·#127 대기).
   스키마 적용·데이터 축적 후엔 그대로 분석으로 직행. 스키마: schema-production.sql.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

# chat_message 컬럼(SoT) — synth와 실 추출이 공유하는 계약
COLUMNS = ("id", "user_id", "session_id", "role", "text", "intent",
           "item_ids", "unanswered", "basis", "created_at")


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        for p in (".env", "../../.env", "services/chat/.env"):
            if os.path.exists(p):
                load_dotenv(p, override=False)
    except ImportError:
        pass


def connect():
    import psycopg
    ci = (f"host={os.environ.get('PGHOST', '192.168.0.8')} port={os.environ.get('PGPORT', '5432')} "
          f"dbname={os.environ.get('PGDATABASE', 'foodbudget')} user={os.environ.get('PGUSER', 'fbapp')} "
          f"password={os.environ.get('PGPASSWORD', '')}")
    return psycopg.connect(ci, connect_timeout=5)


def chat_message_ready(conn) -> bool:
    """chat.chat_message 존재 여부(미마이그레이션 조기 감지)."""
    with conn.cursor() as cur:
        cur.execute("""select count(*) from information_schema.tables
                       where table_schema='chat' and table_name='chat_message'""")
        return cur.fetchone()[0] == 1


def fetch_messages(conn, since: datetime) -> list[dict]:
    """since 이후 대화 메시지 스냅샷(컬럼 dict). 커서 description으로 컬럼 매핑."""
    with conn.cursor() as cur:
        cur.execute(f"""select {', '.join(COLUMNS)} from chat.chat_message
                        where created_at >= %(since)s order by created_at""", {"since": since})
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def load_since(days: int) -> list[dict] | None:
    """최근 N일 메시지. 미마이그레이션/장애면 None(호출측이 skip). 데이터 없으면 []."""
    _load_env()
    since = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        with connect() as conn:
            if not chat_message_ready(conn):
                return None
            return fetch_messages(conn, since)
    except Exception:  # noqa: BLE001 — DB 장애 → skip
        return None

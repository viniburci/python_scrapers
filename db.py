import hashlib
import json
import logging
from urllib.parse import urlparse, urlunparse

import psycopg2

from config import PG_DB, PG_HOST, PG_PASS, PG_PORT, PG_USER

logger = logging.getLogger(__name__)


def _connect():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASS
    )


def init_db():
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notices (
            id TEXT PRIMARY KEY,
            title TEXT,
            org TEXT,
            url TEXT,
            published TEXT,
            raw_hash TEXT,
            found_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cur.close()
    conn.close()
    logger.info("Banco de dados inicializado")


def _md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _normalize_url(raw: str) -> str:
    """Normaliza URL removendo esquema, www, trailing slash, query e fragmento."""
    if not raw:
        return ""
    parsed = urlparse(raw)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/")
    return urlunparse(("https", netloc, path, "", "", ""))


def _generate_id(item: dict) -> str:
    """Gera ID estável: md5(title|org|url_normalizada)."""
    url = _normalize_url(item.get("url", ""))
    title = (item.get("title") or "").strip().lower()
    org = (item.get("org") or "").strip().lower()
    return _md5(title + "|" + org + "|" + url)


def is_new_and_save(item: dict) -> bool:
    uid = _generate_id(item)
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM notices WHERE id = %s", (uid,))
        if cur.fetchone():
            return False
        cur.execute(
            "INSERT INTO notices (id, title, org, url, published, raw_hash) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                uid,
                item.get("title"),
                item.get("org"),
                item.get("url"),
                item.get("published"),
                _md5(json.dumps(item, ensure_ascii=False, sort_keys=True)),
            ),
        )
        conn.commit()
        return True
    finally:
        cur.close()
        conn.close()

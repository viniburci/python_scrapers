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
    if not raw:
        return ""
    parsed = urlparse(raw)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/")
    return urlunparse(("https", netloc, path, "", "", ""))


def generate_id(item: dict) -> str:
    """Gera ID estavel: md5(title|org|url_normalizada)."""
    url = _normalize_url(item.get("url", ""))
    title = (item.get("title") or "").strip().lower()
    org = (item.get("org") or "").strip().lower()
    return _md5(title + "|" + org + "|" + url)


def get_known_ids(items: list[dict]) -> set[str]:
    """Um unico SELECT retorna quais IDs da lista ja existem no banco."""
    if not items:
        return set()
    ids = [generate_id(item) for item in items]
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM notices WHERE id = ANY(%s)", (ids,))
        return {row[0] for row in cur.fetchall()}
    finally:
        cur.close()
        conn.close()


def save_many(items: list[dict]) -> None:
    """Insere multiplos itens em lote. Ignora conflitos (ON CONFLICT DO NOTHING)."""
    if not items:
        return
    rows = []
    for item in items:
        uid = generate_id(item)
        rows.append((
            uid,
            item.get("title"),
            item.get("org"),
            item.get("url"),
            item.get("published"),
            _md5(json.dumps(item, ensure_ascii=False, sort_keys=True)),
        ))
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.executemany(
            "INSERT INTO notices (id, title, org, url, published, raw_hash) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            rows,
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

import sqlite3
import os
from datetime import datetime
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cards.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                card_name       TEXT NOT NULL,
                year            INTEGER,
                sport           TEXT,
                card_set        TEXT,
                card_number     TEXT,
                variation       TEXT,
                player          TEXT,
                psa_pop_10      INTEGER DEFAULT 0,
                psa_pop_9       INTEGER DEFAULT 0,
                psa_pop_8       INTEGER DEFAULT 0,
                psa_pop_7       INTEGER DEFAULT 0,
                psa_pop_6       INTEGER DEFAULT 0,
                psa_pop_5       INTEGER DEFAULT 0,
                psa_pop_4       INTEGER DEFAULT 0,
                psa_pop_3       INTEGER DEFAULT 0,
                psa_pop_2       INTEGER DEFAULT 0,
                psa_pop_1       INTEGER DEFAULT 0,
                psa_pop_auth    INTEGER DEFAULT 0,
                psa_total_pop   INTEGER DEFAULT 0,
                gem_rate        REAL DEFAULT 0.0,
                ebay_avg_price  REAL DEFAULT 0.0,
                ebay_low_price  REAL DEFAULT 0.0,
                ebay_high_price REAL DEFAULT 0.0,
                ebay_sold_count INTEGER DEFAULT 0,
                psa_url         TEXT,
                ebay_search_query TEXT,
                notes           TEXT,
                date_added      TEXT,
                last_updated    TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ebay_listings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id     INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                title       TEXT,
                price       REAL,
                sold_date   TEXT,
                listing_url TEXT,
                condition   TEXT,
                fetched_at  TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_card ON ebay_listings(card_id)")


def add_card(data: dict) -> int:
    data.setdefault("date_added", datetime.now().isoformat(timespec="seconds"))
    data.setdefault("last_updated", data["date_added"])
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    with _connect() as conn:
        cur = conn.execute(f"INSERT INTO cards ({cols}) VALUES ({placeholders})", list(data.values()))
        return cur.lastrowid


def update_card(card_id: int, data: dict):
    data["last_updated"] = datetime.now().isoformat(timespec="seconds")
    sets = ", ".join(f"{k} = ?" for k in data.keys())
    with _connect() as conn:
        conn.execute(f"UPDATE cards SET {sets} WHERE id = ?", [*data.values(), card_id])


def delete_card(card_id: int):
    with _connect() as conn:
        conn.execute("DELETE FROM ebay_listings WHERE card_id = ?", (card_id,))
        conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))


def save_ebay_listings(card_id: int, listings: list[dict]):
    now = datetime.now().isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute("DELETE FROM ebay_listings WHERE card_id = ?", (card_id,))
        for item in listings:
            item["card_id"] = card_id
            item["fetched_at"] = now
            cols = ", ".join(item.keys())
            placeholders = ", ".join(["?"] * len(item))
            conn.execute(f"INSERT INTO ebay_listings ({cols}) VALUES ({placeholders})", list(item.values()))


def get_ebay_listings(card_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM ebay_listings WHERE card_id = ? ORDER BY sold_date DESC", (card_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def search_cards(filters: Optional[dict] = None) -> list[dict]:
    """Search with optional filters dict. All filters are AND'd together."""
    where_clauses = []
    params = []

    if filters:
        text = filters.get("text", "").strip()
        if text:
            like = f"%{text}%"
            where_clauses.append(
                "(card_name LIKE ? OR player LIKE ? OR card_set LIKE ? OR variation LIKE ? OR notes LIKE ?)"
            )
            params.extend([like, like, like, like, like])

        for field in ("sport", "year", "card_set", "variation", "card_number"):
            val = filters.get(field, "").strip() if isinstance(filters.get(field), str) else filters.get(field)
            if val:
                where_clauses.append(f"{field} = ?")
                params.append(val)

        year_from = filters.get("year_from")
        year_to = filters.get("year_to")
        if year_from:
            where_clauses.append("year >= ?")
            params.append(int(year_from))
        if year_to:
            where_clauses.append("year <= ?")
            params.append(int(year_to))

        gem_min = filters.get("gem_rate_min")
        gem_max = filters.get("gem_rate_max")
        if gem_min is not None:
            where_clauses.append("gem_rate >= ?")
            params.append(float(gem_min))
        if gem_max is not None:
            where_clauses.append("gem_rate <= ?")
            params.append(float(gem_max))

        price_min = filters.get("price_min")
        price_max = filters.get("price_max")
        if price_min is not None:
            where_clauses.append("ebay_avg_price >= ?")
            params.append(float(price_min))
        if price_max is not None:
            where_clauses.append("ebay_avg_price <= ?")
            params.append(float(price_max))

        pop_min = filters.get("pop_10_min")
        if pop_min is not None:
            where_clauses.append("psa_pop_10 >= ?")
            params.append(int(pop_min))

    sql = "SELECT * FROM cards"
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY last_updated DESC"

    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_card(card_id: int) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        return dict(row) if row else None


def get_distinct_values(field: str) -> list:
    safe_fields = {"sport", "card_set", "variation", "year", "player"}
    if field not in safe_fields:
        return []
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT {field} FROM cards WHERE {field} IS NOT NULL AND {field} != '' ORDER BY {field}"
        ).fetchall()
        return [r[0] for r in rows]

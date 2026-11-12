"""ReMind by Her: sign-up storage.

One adapter, two drivers:
  * DATABASE_URL unset  -> SQLite at data/remind.sqlite (created on first use, no setup)
  * DATABASE_URL=postgresql://user:pass@host:5432/db -> PostgreSQL (needs `pip install "psycopg[binary]"`)

The schema is created automatically on first use for either driver.
"""

from __future__ import annotations

import os
import pathlib
import re
import sqlite3
import threading
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
SQLITE_PATH = pathlib.Path(os.getenv("REMIND_SQLITE_PATH", HERE.parent / "data" / "remind.sqlite"))

AGE_RANGES = ("Under 40", "40–44", "45–49", "50–54", "55–59", "60+")
LANGUAGES = ("English", "Hindi", "Kannada", "Other")
HEARD_FROM = ("Instagram", "WhatsApp", "A friend or family member", "MyStree clinic", "My doctor", "Other")
UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")
CONSENT_TEXT = "I agree to be added to the ReMind WhatsApp community. I understand other members may see my number."

# Every column, in table order (id is assigned by the database).
COLUMNS = ("full_name", "whatsapp_normalized", "email", "age_range", "city", "preferred_language", "heard_from",
           "consent_community", "consent_text", *UTM_KEYS, "page_url", "consultation_status", "submitted_at", "updated_at")

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


# ---------------------------------------------------------------- validation
def normalize_phone(raw: str) -> str | None:
    """'+91 98765 43210', '098765 43210', '9876543210' -> '+919876543210'; None if not an Indian mobile."""
    d = re.sub(r"\D", "", raw or "")
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    return f"+91{d}" if re.fullmatch(r"[6-9]\d{9}", d) else None


def _text(v, limit: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit + 1]


def validate(payload: dict) -> tuple[dict | None, dict]:
    """Form payload (the page's field names) -> (clean record, errors by field name)."""
    errors: dict[str, str] = {}
    name = _text(payload.get("name"), 60)
    if not 2 <= len(name) <= 60:
        errors["name"] = "Please enter your full name."
    phone = normalize_phone(str(payload.get("phone", "")))
    if not phone:
        errors["phone"] = "Please enter a valid 10-digit mobile number."
    email = _text(payload.get("email"), 120).lower() or None
    if email and (len(email) > 120 or not _EMAIL.match(email)):
        errors["email"] = "Please check your email address."
    age = str(payload.get("age") or "")
    if age not in AGE_RANGES:
        errors["age"] = "Please choose your age range."
    city = _text(payload.get("city"), 60)
    if not 2 <= len(city) <= 60:
        errors["city"] = "Please enter your city."
    lang = str(payload.get("language") or "") or None
    if lang and lang not in LANGUAGES:
        errors["language"] = "Please choose a language from the list."
    heard = str(payload.get("source") or "") or None
    if heard and heard not in HEARD_FROM:
        errors["source"] = "Please choose an option from the list."
    if payload.get("consent") is not True:
        errors["consent"] = "Please agree so we can add you to the group."
    if errors:
        return None, errors
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    rec = {
        "full_name": name, "whatsapp_normalized": phone, "email": email, "age_range": age, "city": city,
        "preferred_language": lang, "heard_from": heard, "consent_community": True, "consent_text": CONSENT_TEXT,
        **{k: (_text(payload.get(k), 200)[:200] or None) for k in UTM_KEYS},
        "page_url": (_text(payload.get("page_url"), 500)[:500] or None),
        "consultation_status": "PENDING_WHATSAPP", "submitted_at": now, "updated_at": now,
    }
    return rec, {}


# ---------------------------------------------------------------- storage
class Store:
    """save(record) -> (id, duplicate). A WhatsApp number already on file is not stored twice:
    its updated_at is refreshed and `duplicate` is True."""

    def __init__(self, url: str | None = None):
        self.url = (url if url is not None else os.getenv("DATABASE_URL", "")).strip()
        self.driver = "postgres" if self.url.startswith(("postgres://", "postgresql://")) else "sqlite"
        self._lock = threading.Lock()
        self._ready = False

    # -- connections
    def _sqlite(self):
        SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(SQLITE_PATH, timeout=10)
        con.execute("PRAGMA journal_mode=WAL")
        con.row_factory = sqlite3.Row
        return con

    def _pg(self):
        import psycopg  # only needed for PostgreSQL
        from psycopg.rows import dict_row
        return psycopg.connect(self.url, row_factory=dict_row, connect_timeout=10)

    def ensure_schema(self):
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            if self.driver == "sqlite":
                with self._sqlite() as con:
                    con.executescript((HERE / "schema.sqlite.sql").read_text(encoding="utf-8"))
            else:
                with self._pg() as con:
                    con.execute((HERE / "schema.postgres.sql").read_text(encoding="utf-8"))
            self._ready = True

    # -- writes
    def save(self, rec: dict) -> tuple[int, bool]:
        self.ensure_schema()
        if self.driver == "postgres":
            cols = ", ".join(COLUMNS)
            ph = ", ".join(f"%({c})s" for c in COLUMNS)
            sql = (f"INSERT INTO registrations ({cols}) VALUES ({ph}) "
                   "ON CONFLICT (whatsapp_normalized) DO UPDATE SET updated_at = EXCLUDED.updated_at "
                   "RETURNING id, (xmax = 0) AS inserted")
            with self._pg() as con:
                row = con.execute(sql, rec).fetchone()
            return int(row["id"]), not row["inserted"]
        rec = {**rec, "consent_community": 1}
        with self._lock, self._sqlite() as con:
            cur = con.execute("SELECT id FROM registrations WHERE whatsapp_normalized = ?", (rec["whatsapp_normalized"],)).fetchone()
            if cur:
                con.execute("UPDATE registrations SET updated_at = ? WHERE id = ?", (rec["updated_at"], cur["id"]))
                return int(cur["id"]), True
            cols = ", ".join(COLUMNS)
            cur = con.execute(f"INSERT INTO registrations ({cols}) VALUES ({', '.join('?' for _ in COLUMNS)})",
                              tuple(rec[c] for c in COLUMNS))
            return int(cur.lastrowid), False

    # -- reads (for the export and the admin CSV)
    def rows(self) -> list[dict]:
        self.ensure_schema()
        sql = f"SELECT id, {', '.join(COLUMNS)} FROM registrations ORDER BY id"
        if self.driver == "postgres":
            with self._pg() as con:
                return [dict(r) for r in con.execute(sql).fetchall()]
        with self._sqlite() as con:
            return [dict(r) for r in con.execute(sql).fetchall()]

    def health(self) -> dict:
        try:
            self.ensure_schema()
            sql = "SELECT COUNT(*) AS n FROM registrations"
            if self.driver == "postgres":
                with self._pg() as con:
                    n = con.execute(sql).fetchone()["n"]
            else:
                with self._sqlite() as con:
                    n = con.execute(sql).fetchone()["n"]
            return {"ok": True, "driver": self.driver, "registrations": int(n)}
        except Exception as exc:  # report, never crash the health check
            return {"ok": False, "driver": self.driver, "error": type(exc).__name__}

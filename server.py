"""ReMind by Her: page + sign-up API. Python standard library only (PostgreSQL also needs psycopg).

    python server.py [port]                     # SQLite at data/remind.sqlite (default, no setup)
    DATABASE_URL=postgresql://... python server.py   # every sign-up goes straight into PostgreSQL

Routes
    GET  /, /index.html, /assets/*      the landing page (nothing else on disk is served)
    POST /api/register                  the Join form (JSON)
    GET  /api/health                    {"ok", "driver", "registrations"}
    GET  /api/admin/registrations.csv   all sign-ups as CSV; needs REMIND_ADMIN_TOKEN set on the
                                        server and sent as  Authorization: Bearer <token>

Env: PORT, HOST (default 127.0.0.1), DATABASE_URL, REMIND_ADMIN_TOKEN, TRUST_PROXY=1 (behind a proxy).
"""

from __future__ import annotations

import csv
import hmac
import io
import json
import mimetypes
import os
import pathlib
import sys
import time
from collections import defaultdict, deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, unquote

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))
from db import COLUMNS, SQLITE_PATH, Store, validate  # noqa: E402

STORE = Store()
MAX_BODY = 8 * 1024
RATE = (8, 600)                      # 8 sign-ups per IP per 10 minutes
_hits: dict[str, deque] = defaultdict(deque)
mimetypes.add_type("image/webp", ".webp")


def csv_cell(v) -> str:
    """Spreadsheet-safe: a cell starting with = + - @ is never run as a formula."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


class Handler(BaseHTTPRequestHandler):
    server_version = "ReMind/1"

    # ---------------------------------------------------------- helpers
    def _headers(self, status: int, ctype: str, length: int, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def _json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _ip(self) -> str:
        if os.getenv("TRUST_PROXY") == "1" and self.headers.get("X-Forwarded-For"):
            return self.headers["X-Forwarded-For"].split(",")[0].strip()
        return self.client_address[0]

    def _limited(self) -> bool:
        q, now = _hits[self._ip()], time.monotonic()
        while q and now - q[0] > RATE[1]:
            q.popleft()
        if len(q) >= RATE[0]:
            return True
        q.append(now)
        return False

    def log_message(self, fmt, *args):  # keep form data out of logs: method, path, status only
        sys.stderr.write(f"{self.log_date_time_string()} {self.command} {urlsplit(self.path).path} {args[1] if len(args) > 1 else ''}\n")

    # ---------------------------------------------------------- GET
    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        if path == "/api/health":
            return self._json(200, {**STORE.health(), "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        if path == "/api/admin/registrations.csv":
            return self._admin_csv()
        if path in ("/", "/index.html"):
            return self._file(ROOT / "index.html")
        if path.startswith("/assets/"):
            target = (ROOT / path.lstrip("/")).resolve()
            if target.is_file() and (ROOT / "assets") in target.parents:
                return self._file(target)
        self._json(404, {"ok": False, "error": "Not found."})

    def _file(self, f: pathlib.Path):
        data = f.read_bytes()
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if ctype.startswith("text/"):
            ctype += "; charset=utf-8"
        self._headers(200, ctype, len(data))
        self.wfile.write(data)

    def _admin_csv(self):
        token = os.getenv("REMIND_ADMIN_TOKEN", "")
        sent = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not token:
            return self._json(404, {"ok": False, "error": "Not found."})
        if not hmac.compare_digest(sent.encode(), token.encode()):
            return self._json(401, {"ok": False, "error": "Unauthorised."})
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(("id", *COLUMNS))
        for r in STORE.rows():
            w.writerow([csv_cell(r.get(c)) for c in ("id", *COLUMNS)])
        body = ("﻿" + buf.getvalue()).encode("utf-8")   # BOM: Excel opens UTF-8 (en dashes) correctly
        self._headers(200, "text/csv; charset=utf-8", len(body),
                      {"Content-Disposition": 'attachment; filename="remind-registrations.csv"'})
        self.wfile.write(body)

    # ---------------------------------------------------------- POST
    def do_POST(self):
        if urlsplit(self.path).path != "/api/register":
            return self._json(404, {"ok": False, "error": "Not found."})
        if "application/json" not in self.headers.get("Content-Type", ""):
            return self._json(415, {"ok": False, "error": "Send JSON."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 < length <= MAX_BODY:
            return self._json(413 if length > MAX_BODY else 400, {"ok": False, "error": "Request is empty or too large."})
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            assert isinstance(payload, dict)
        except Exception:
            return self._json(400, {"ok": False, "error": "Could not read the form."})
        if str(payload.get("website") or "").strip():          # honeypot: look successful, store nothing
            return self._json(200, {"ok": True, "duplicate": False})
        if self._limited():
            return self._json(429, {"ok": False, "error": "Too many attempts. Please try again in a few minutes."})
        rec, errors = validate(payload)
        if errors:
            return self._json(400, {"ok": False, "errors": errors})
        try:
            rid, duplicate = STORE.save(rec)
        except Exception as exc:
            sys.stderr.write(f"register failed: {type(exc).__name__}: {exc}\n")
            return self._json(503, {"ok": False, "error": "We could not save your details just now."})
        self._json(200, {"ok": True, "duplicate": duplicate, "id": rid})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.getenv("PORT", "4321"))
    host = os.getenv("HOST", "127.0.0.1")
    STORE.ensure_schema()
    where = "PostgreSQL" if STORE.driver == "postgres" else f"SQLite ({SQLITE_PATH})"
    print(f"ReMind on http://{host}:{port}  ·  sign-ups -> {where}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()

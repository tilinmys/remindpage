# ReMind by Her

The landing page and sign-up backend for **ReMind by Her**, a six-week, psychologist-led cognitive wellness program by MyStree for women in perimenopause and menopause.

## Run it

```bash
python server.py            # http://127.0.0.1:4321
```

Python 3.10 or newer. The server needs no packages: it serves the page and saves sign-ups to SQLite at `data/remind.sqlite`, which is created on first use.

To save sign-ups straight into PostgreSQL instead:

```bash
pip install -r requirements.txt
DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/DBNAME" python server.py
```

## What's here

| Path | Contents |
| --- | --- |
| `index.html` | The page: HTML, CSS and JS in one file, using only white and burgundy below the hero. |
| `assets/` | Images, the vector logo mark (`mark.svg`) and the favicon. |
| `server.py` | Serves the page and the API: `POST /api/register`, `GET /api/health`, and a token-protected CSV export. |
| `backend/` | Validation and storage (`db.py`), the SQLite and PostgreSQL schemas, and the one-command export to PostgreSQL. |
| `BACKEND.md` | Notes for the database engineer: export, table, CSV and server behaviour. |

## Moving sign-ups to PostgreSQL

```bash
python backend/export_to_postgres.py "postgresql://USER:PASSWORD@HOST:5432/DBNAME"
```

See [BACKEND.md](BACKEND.md) for details.

## Hosting

Sign-ups are saved by `server.py`, so the site needs a host that can run Python, such as a small VM, Render or Railway. Static hosting alone can serve the page, but the Join form will then show an error instead of saving.

Set these on the host:

- `HOST=0.0.0.0` and `PORT`
- `DATABASE_URL` to use PostgreSQL
- `REMIND_ADMIN_TOKEN` for the CSV export
- `TRUST_PROXY=1` when running behind a proxy

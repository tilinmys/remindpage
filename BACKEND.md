# ReMind sign-ups: for the database engineer

Every "Join ReMind" form submission is stored in one table, `registrations`.

## Move everything into PostgreSQL (one command)

```bash
python backend/export_to_postgres.py "postgresql://USER:PASSWORD@HOST:5432/DBNAME"
```

That one command:

- creates the table and its indexes if they are missing;
- copies every sign-up from the local SQLite file (`data/remind.sqlite`);
- runs as a single transaction, so either everything is copied or nothing is.

It is safe to run again. Nobody is duplicated: a WhatsApp number that already exists is updated only when the local copy is newer.

It needs the PostgreSQL driver: `pip install "psycopg[binary]"`.

To keep the password out of your shell history, set `DATABASE_URL` and run the command with no argument.

**No Python driver?** Export a plain `.sql` file and load it with `psql`:

```bash
python backend/export_to_postgres.py --sql remind_export.sql
psql "$DATABASE_URL" -f remind_export.sql
```

## Or send sign-ups straight to PostgreSQL

```bash
DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/DBNAME" python server.py 4321
```

Each new sign-up is then written directly to PostgreSQL. The table is created on first start. SQLite is used only when `DATABASE_URL` is not set.

## Get the data as a spreadsheet

Start the server with `REMIND_ADMIN_TOKEN` set to a long random secret, then:

```bash
curl -H "Authorization: Bearer $REMIND_ADMIN_TOKEN" http://HOST:4321/api/admin/registrations.csv -o registrations.csv
```

The CSV is UTF-8 and opens correctly in Excel. Cells that start with `=`, `+`, `-` or `@` get a leading `'`, so a sign-up can never run a formula. Without the token set, this route does not exist (404).

## The table

| Column | Notes |
| --- | --- |
| `id` | assigned by the database |
| `full_name` | 2 to 60 characters |
| `whatsapp_normalized` | unique; always `+91` followed by a 10-digit Indian mobile number. The same person typing `098765…` or `+91 98765…` is caught as a duplicate. |
| `email` | optional; stored lowercase |
| `age_range` | `Under 40`, `40–44`, `45–49`, `50–54`, `55–59` or `60+` (en dash, so the database must be UTF8) |
| `city` | 2 to 60 characters |
| `preferred_language` | optional: `English`, `Hindi`, `Kannada` or `Other` |
| `heard_from` | optional |
| `consent_community` | always true; a row cannot be stored without consent |
| `consent_text` | the exact sentence she agreed to |
| `utm_source` … `utm_content`, `page_url` | campaign tracking, from the page URL |
| `consultation_status` | `PENDING_WHATSAPP` on sign-up; update it as the team follows up |
| `submitted_at` | first sign-up time (UTC) |
| `updated_at` | most recent submission (UTC) |

The full definitions are in `backend/schema.postgres.sql` and `backend/schema.sqlite.sql`. The two match column for column, rule for rule.

## How the server behaves

| Route | Behaviour |
| --- | --- |
| `POST /api/register` | The form's JSON. Returns `{ok, duplicate, id}`, or a 400 with `errors` keyed by field. Returns 429 after 8 attempts from one IP in 10 minutes. A filled-in honeypot field is answered "ok" but nothing is stored. |
| `GET /api/health` | `{ok, driver: "sqlite" \| "postgres", registrations}` |

- Only `index.html` and `assets/` are served. The database file, the code and `drafts/` can never be downloaded.
- Logs record the method, path and status only, never form data.
- Behind a reverse proxy, set `TRUST_PROXY=1` so rate limiting uses the client's real IP. Set `HOST=0.0.0.0` to listen beyond localhost.

Everything above was tested end to end against PostgreSQL 18 and SQLite (2026-11-11):

- the export, a repeat run, a newer local edit, and the `.sql` file loaded with `psql`;
- the database constraints;
- live mode through the real form in a browser.

# jarl-member-search

Batch-check whether a list of amateur-radio callsigns belong to **JARL**
(Japan Amateur Radio League). Pulls callsigns from a typed list, an
**ADI/ADIF** log file, or your **QRZ Logbook** directly, filters down to
Japanese-prefix callsigns, queries the official
[JARL Member Search](https://www.jarl.com/Page/Search/MemberSearch.aspx?Language=Jp)
20 at a time, caches results locally, and exports a CSV.

> Read [`PROJECT_CHARTER.md`](PROJECT_CHARTER.md) before contributing.
> The charter spells out the scope and explicit non-goals — please don't
> expand the project without proposing a charter update.

## Features

- 📝 **Three input modes**: paste callsigns, upload `.adi`/`.adif`, or pull
  from QRZ Logbook by date range
- 🇯🇵 **Smart filtering**: standard Japanese prefixes (`JA-JS`, `7J-7N`,
  `8J/8N`) with portable-suffix stripping (`JA1RL/P` → `JA1RL`)
- ⚡ **JARL batching**: groups 20 callsigns per request (the form's native
  limit), with 1 req/s default rate limit
- 💾 **SQLite cache**: 30-day TTL by default; `unknown` results are
  never cached (per charter §7.5)
- 🔐 **Secrets gate**: `scripts/check_secrets.sh` blocks accidental commits
  of QRZ API keys or other credentials
- ✅ **Self-verify**: `scripts/verify.py` runs three real-world checks
  (positive, negative, end-to-end) — exit code 0 on green

## Result semantics

JARL returns one of five strings; we map them as follows:

| JARL says                              | `is_jarl_member` | Notes                                       |
| -------------------------------------- | ---------------- | ------------------------------------------- |
| `○ Yes` / `○ YES`                      | `yes`            | Member, QSL forwardable                     |
| `○ No`  / `○ NO`                       | `yes`            | Still a member (just no QSL forwarding)     |
| `× ` (full-width cross)                | `no`             | Not a member, or opted out of directory     |
| `○ Yes via {callsign}`                 | `yes`            | QSL forwarded via that callsign (`qsl_via`) |
| `○ YES **/{callsign}/** via {callsign}`| `yes`            | Foreign operation, same                     |
| _(no result / network error)_          | `unknown`        | UI highlights — open JARL site manually     |

⚠️ `unknown` ≠ non-member. Always treat it as "we don't know yet". The cache
intentionally refuses to store unknowns.

## Install

Requires Python **3.9+** (developed on 3.9).

```bash
git clone https://github.com/<your-username>/jarl-member-search.git
cd jarl-member-search
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then edit and add your QRZ key
```

## Run

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000> and use the web UI. From there you can:

- paste callsigns
- upload an `.adi`/`.adif` file
- enter a QRZ Logbook API key (or leave blank to use `QRZ_API_KEY` from
  `.env`) and optionally a date range
- click **Search JARL** for an HTML result table, or **Download CSV**
- filter results (Members only / Non-members / Unknown) and sort columns

### Configuration

All settings live in `.env`:

| Variable                  | Default | Meaning                                  |
| ------------------------- | ------- | ---------------------------------------- |
| `QRZ_API_KEY`             | _none_  | See "Getting a QRZ Logbook API key" below |
| `JARL_RATE_LIMIT_SECONDS` | `1.0`   | Sleep between JARL batches (20 calls/batch) |
| `CACHE_TTL_DAYS`          | `30`    | How long cached entries stay fresh        |

### Getting a QRZ Logbook API key

⚠️ **The QRZ Logbook API requires a paid QRZ XML Subscriber account**
(~US$35/year). Free QRZ accounts can use the logbook in the browser but
**cannot** call the HTTP API. If you see

> `user does not have a valid QRZ subscription to use this function`

that's the cause. The other two input modes — paste a callsign list, or
upload an ADI file exported from your logger — work for everyone and need
no subscription.

If you do have an XML Subscriber account:

1. The key is **per logbook**, not per account. Go to
   <https://logbook.qrz.com>, open your logbook, click **Settings** →
   look for "API key" / "Web Service API".
2. The logbook must have at least one QSO in it.

Errors from QRZ are surfaced verbatim in the UI — `invalid api key XXXX`,
`STATUS: AUTH`, the subscription message above — so you can tell exactly
which case you're hitting.

### Working around the QRZ subscription requirement

Every desktop / web logger can export ADI/ADIF: Cloudlog, Log4OM, N1MM,
HRD, JTDX, WSJT-X, Ham Radio Deluxe, etc. Export your log, then drag the
file into the "Or upload ADI/ADIF file" box. Same result, no subscription
needed.

## Be kind to JARL

The default rate limit is one request per second, and each request can carry
up to 20 callsigns — so even a 1000-callsign log finishes in ~50 seconds.
Please do not lower the limit or fire requests in parallel; JARL is a
non-commercial association running this service for the community.

## Verify before shipping

```bash
./scripts/check_secrets.sh   # no committed credentials
python scripts/verify.py     # three real-world checks (Charter §3.2)
pytest tests/                # unit tests
```

## License

MIT — see [`LICENSE`](LICENSE).

## Acknowledgements

- JARL for running the public member search
- QRZ.com for the Logbook API
- The ADIF working group for keeping the format mercifully simple

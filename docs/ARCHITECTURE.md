# Personal Work Agent — Architecture

Status: MVP (startup + tray + encrypted vault + tracking + timeline + PIN lock + daily report).
Agent chat and the Jira link-out are present in basic local form; everything else is an extension point.

## 1. Principles

1. **Local-first, closed by default.** No network I/O unless the user configures an AI provider
   *and* explicitly allows that use (`ai.allow_chat`, `ai.allow_reports`). No telemetry, no sync.
2. **Nothing readable at rest.** Every activity, report, task and secret is AEAD-encrypted inside a
   single SQLite file (`vault.db`). Logs never contain window titles, URLs or report text.
3. **Semantic, not raw.** We sample the foreground window every few seconds but persist only
   *activities* (a continuous span of the same app/title), never key or mouse events.
4. **Evidence over prose.** Every report bullet carries the activity spans that justify it.
   Inferred items (blockers, escalation suggestions) are labelled as such.
5. **Pure core, thin shell.** Crypto, storage, coalescing, context extraction, sessions,
   reporting, scheduling and the agent are plain Python with no Qt or Win32 imports, so they are
   unit-tested directly. Qt and Win32 live only in `ui/`, `system/` and `tracking/win32.py`.

## 2. Module map

```
src/workagent/
  config.py           typed config (JSON in data dir) — non-sensitive settings only
  paths.py            data dir resolution (WORKAGENT_HOME override for dev/tests)
  models.py           Activity, Task, Report, ReportItem, Evidence
  crypto/primitives.py   Argon2id, AES-256-GCM, HKDF, HMAC, X25519 sealing (via `cryptography`, `argon2-cffi`)
  storage/vault.py       encrypted document store on SQLite; lock / unlock / change PIN / sealed inbox
  storage/repositories.py typed repos: activities, reports, tasks, secrets
  tracking/win32.py      ctypes probe: foreground window, process, idle time, session lock
  tracking/browser.py    optional UI-Automation URL reader (off by default)
  tracking/privacy.py    blocklists, privacy mode, secret redaction, URL sanitising
  tracking/coalescer.py  samples → activities (idle backdating, midnight split, periodic flush)
  tracking/collector.py  background thread wiring probe → privacy → coalescer → sink
  context/extractor.py   app/title/url → category, project, file, tickets, domain
  context/sessions.py    activities → work sessions; day summary
  reports/generator.py   evidence-based 5-section daily report (+ optional LLM polish)
  agent/agent.py         local Q&A over history (+ optional LLM with explicit consent)
  ai/providers.py        none | openai-compatible (Ollama/LM Studio) | anthropic — stdlib HTTP
  integrations/jira.py   ticket-key helpers, browse URL
  scheduler.py           pure decision logic: report time, auto-lock, day rollover
  system/startup.py      HKCU\...\Run registration
  app.py                 composition root (AppController) — the only place modules meet
  ui/                    PySide6 window, tray, PIN screens, pages; UiRouter picks desktop or web
  web/api.py             JSON API over the controller (transport-free, unit-tested)
  web/server.py          stdlib HTTP server on 127.0.0.1 + static dark UI (web/static, no CDN)
```

## 3. Data flow

```
 foreground window ─┐
 idle / lock state ─┼─▶ Probe (2s) ─▶ PrivacyFilter ─▶ Coalescer ─▶ ActivityRepository ─▶ Vault
 (opt) browser URL ─┘                 (block/redact)   (activities)   (upsert)              │
                                                                                            ▼
         UI ◀── AppController ◀── Context Engine (sessions, summary) ◀── reads (unlocked only)
                     │                    │
                     ├── Scheduler ──▶ ReportGenerator ──▶ ReportRepository ──▶ Vault
                     └── Agent ──▶ (optional) AI provider, only with consent
```

Raw samples are never stored. The coalescer keeps the open activity in memory and upserts it on
change and every `flush_seconds` (default 30 s), so a crash loses at most that much.

## 4. Vault design

Single file `vault.db`:

| table   | columns                                   | purpose |
|---------|-------------------------------------------|---------|
| meta    | key, value                                | format version, KDF params+salt, wrapped keys, public key |
| records | ctag, id, dtag, blob                      | documents encrypted with the record key |
| inbox   | seq, epk, blob                            | documents written while locked (sealed to the vault public key) |

Key hierarchy:

```
PIN ──Argon2id(salt, t=3, m=64 MiB, p=4)──▶ KEK
KEK ──AES-256-GCM──▶ wraps DK (random 256-bit data key)     ← change PIN = re-wrap DK only
DK  ──HKDF──▶ record key   (AES-256-GCM per document, random 96-bit nonce)
DK  ──HKDF──▶ index key    (HMAC-SHA256 for collection/day tags — no plaintext dates/names)
DK  ──HKDF──▶ sealing key  (wraps the X25519 private key)
X25519 public key (plaintext in meta) ──▶ used while LOCKED
```

* **Locked writes.** While locked the app has only the public key. Each write is sealed:
  ephemeral X25519 → HKDF → AES-256-GCM, appended to `inbox`. Nothing written while locked can
  be read back without the PIN. On unlock the inbox is decrypted and migrated into `records`
  in order (later writes win), then deleted, in one transaction.
* **Integrity.** AAD binds: wrapped DK ↔ KDF params; wrapped private key ↔ public key; record ↔
  (collection tag, id); sealed record ↔ ephemeral key. Decrypted records must also name the
  collection they were requested from. On unlock the stored public key is checked against the
  decrypted private key, so a swapped public key is detected.
* **No recovery.** There is no escrow or recovery key. A lost PIN means the vault is unreadable.
* **Metadata that remains visible:** number of rows, approximate sizes, and the count of locked
  writes. Times, app names, titles, collections and days are not visible.
* **Known limits:** Python cannot reliably wipe key material from memory; a process-memory
  attacker on an unlocked session is out of scope. An attacker with write access to the vault file
  can delete or roll back rows (not read or forge them). A short numeric PIN is brute-forceable
  offline despite Argon2id — the UI requires ≥ 6 characters and recommends a passphrase.

## 5. States

* Tracking: `TRACKING` | `PAUSED` (nothing recorded) | `PRIVACY` (time + app only, no titles/URLs).
* Vault: `UNINITIALIZED` → (set PIN) → `UNLOCKED` ⇄ `LOCKED`.
  Locking happens on demand, on Windows session lock (default on) and after N idle minutes.
  Tracking continues in every vault state.

## 6. Privacy rules (defaults)

* Blocked apps (password managers, authenticators, credential prompts) → recorded as
  `private` with no title.
* Blocked title keywords / domains (password, OTP, 2FA, banking, private key, InPrivate,
  Incognito, …) → `private`.
* Redaction of anything that looks like a secret in titles: JWTs, API-key prefixes
  (`sk-`, `ghp_`, `AKIA`, `xox?-`), long hex/base64 runs, `key=value` secrets, 6–8 digit codes.
* URLs: off by default. If enabled, mode `domain` keeps only the host; `full` drops query and
  fragment.
* Screenshots / OCR: not implemented in MVP (interface intentionally absent rather than stubbed).

## 7. Daily report

Sections: Progress Today · Issues Found · Block · Need Support / Escalation · Plan Tomorrow.
Rules (see `reports/generator.py`): progress from project/ticket time; issues from error/debug
signals in titles; blocks from long repeated investigation of the same issue or tasks marked
blocked; support from tasks flagged and very long blocks; plan from open tasks and unfinished
tickets. Each item lists evidence spans. The draft is generated automatically at
`report.time` (or on first unlock after it), and is saved as an editable Markdown draft that
the user reviews before exporting.

## 8. Web UI

`ui_mode` = `desktop` (Qt window) or `web` (browser), switchable live from either Settings page.
The tray stays in both modes. The web server runs only in web mode and:

* binds 127.0.0.1 only; port `web_port` (falls back to a free port if taken);
* requires a random per-run token in an `X-WA-Token` header on every `/api` call. The tray opens
  `http://127.0.0.1:PORT/#t=TOKEN` — the fragment never reaches the server or logs; the page keeps
  it in `sessionStorage`. The custom header forces a CORS preflight that is always refused (CSRF);
* rejects foreign `Host` (DNS rebinding) and foreign `Origin`; serves a fixed allow-list of files;
  strict CSP (`default-src 'none'`, no inline script/style), `no-store`, no request logging;
* throttles PIN attempts (exponential back-off after 3 failures) and never returns the AI key.

Mutating calls are marshalled onto the Qt thread (`AppController.run_on_main`).

## 9. AI providers

Registry in `ai/providers.py`: none · local OpenAI-compatible (Ollama/LM Studio, editable URL) ·
Mistral · Gemini (OpenAI-compatible endpoint) · Groq · Mangso (`https://ai.mangso.net/v1`) ·
Anthropic · OpenCode CLI. Cloud base URLs are fixed so a key can't be redirected to another host.
Keys are stored per provider in the vault (`ai_key:<provider>`); the API only reports whether one
is set. "Load models" queries the provider's live `/models` (or `opencode models`); the default
lists are only a starting point. The connection test sends a fixed prompt with no user data.

Reports: `compose` mode sends a compact activity log (private spans as duration only), the task
list and the rule draft, and asks for the five numbered sections. Output is rejected — the rule
draft is kept and `ai_error` shown — if a section is missing or a ticket key appears that is not
in the input. `polish` mode only rewords rule items.

OpenCode (`ai/opencode.py`): runs `opencode run --format json --agent plan` in an empty temp dir,
prompt passed as an argument (never written to disk), tools denied via `OPENCODE_PERMISSION`. The
OpenCode free tier (e.g. Big Pickle) refuses modified permissions; for those models the read-only
`plan` agent is used without the deny list (it can still web-fetch), and any tool event kills the
process and discards the answer. Big Pickle runs on OpenCode's servers, so it is treated as cloud.

## 10. Extending

* New collector source: produce `WindowSample`s or feed the coalescer an extra field.
* New integration: add a module under `integrations/`, consume `ActivityRepository`, never Qt.
* New AI provider: implement `AIProvider.complete(system, prompt) -> str` in `ai/providers.py`.

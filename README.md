# Personal Work Agent

A Windows tray app that records what you work on (foreground app/window, idle, lock), keeps it in an
encrypted local vault unlocked by your PIN, shows a timeline, and drafts an evidence-based daily
report. No cloud, no telemetry. Design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Run

Requires Python 3.11+ on Windows.

```
python tasks.py dev      # first run creates .venv and installs; data goes to ./.devdata
python tasks.py test
python tasks.py build    # -> dist/PersonalWorkAgent.exe
```

The built exe stores data in `%LOCALAPPDATA%\PersonalWorkAgent\` (`vault.db`, `config.json`, `logs\`)
and, if enabled at setup, registers itself to start at Windows sign-in.

## Notes

* Two UIs, switchable in Settings (Cài đặt → Giao diện): the desktop window, or a dark web UI served
  only on `127.0.0.1` and opened from the tray. The UI is in Vietnamese. The trợ lý understands both Vietnamese and English. Daily report section
  headings follow the spec (Progress Today, Issues Found, …).
* **Forgotten PIN = unreadable data.** There is no recovery key by design.
* Optional browser URL capture: `pip install .[browser]`, then pick a URL mode in Settings.
* Optional AI (off by default): Mistral, Gemini, Groq, Mangso, Anthropic Claude, a local
  OpenAI-compatible server (Ollama, LM Studio), or the installed OpenCode CLI (e.g. Big Pickle).
  Pick provider + model and paste the key in Settings → AI; keys are stored encrypted per provider.
  Nothing is sent unless you also tick the per-feature consent boxes.

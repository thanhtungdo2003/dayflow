"""Entry point: `python -m workagent [--minimized] [--debug]`."""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="workagent")
    parser.add_argument("--minimized", action="store_true", help="start in the system tray")
    parser.add_argument("--debug", action="store_true", help="verbose logging (no content is logged)")
    parser.add_argument("--self-test", action="store_true",
                        help="check crypto/vault in a temp dir and exit (0 = ok); useful for packaged builds")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    from .ui.application import run  # Qt import deferred so --help works without a display
    return run(start_minimized=args.minimized, debug=args.debug)


def self_test() -> int:
    import tempfile
    from pathlib import Path

    from .storage.vault import Vault

    with tempfile.TemporaryDirectory() as tmp:
        vault = Vault(Path(tmp) / "vault.db").open()  # production KDF parameters
        try:
            vault.initialize("self-test-pin")
            vault.lock()
            vault.put("selftest", "x", {"ok": True}, day="2000-01-01")
            vault.unlock("self-test-pin")
            ok = vault.list("selftest", day="2000-01-01") == [{"ok": True}]
        finally:
            vault.close()
    from .web.server import STATIC_DIR, STATIC_FILES
    ok = ok and all((STATIC_DIR / name).is_file() for name, _ in STATIC_FILES.values())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

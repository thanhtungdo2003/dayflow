import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workagent.storage.vault import Vault  # noqa: E402

# Cheap Argon2 parameters keep the suite fast; production defaults are tested separately.
FAST_KDF = {"time_cost": 1, "memory_kib": 1024, "parallelism": 1}
PIN = "correct-horse"


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKAGENT_HOME", str(tmp_path / "home"))


@pytest.fixture
def vault(tmp_path):
    v = Vault(tmp_path / "vault.db", kdf_defaults=FAST_KDF).open()
    v.initialize(PIN)
    yield v
    v.close()

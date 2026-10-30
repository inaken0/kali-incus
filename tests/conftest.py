"""統合テスト用の道具: 偽 incus を PATH 先頭に置いて bin/kali を実行する。"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
KALI = ROOT / "bin" / "kali"


@dataclass
class Result:
    rc: int
    out: str
    err: str


@dataclass
class Env:
    tmp: Path
    env: dict[str, str] = field(default_factory=dict)

    @property
    def state_path(self) -> Path:
        return self.tmp / "state.json"

    @property
    def state(self) -> dict:
        return json.loads(self.state_path.read_text())

    def set_state(self, instances: dict | None = None, images: list | None = None) -> None:
        self.state_path.write_text(json.dumps({"instances": instances or {}, "images": images or []}))

    def add_instance(self, name: str = "kali", **kw) -> dict:
        inst = {
            "name": name, "status": "Running",
            "config": {"user.kali-incus.managed": "true", "user.kali-incus.provisioned": "true"},
            "devices": {}, "snapshots": [],
        }  # fmt: skip
        inst.update(kw)
        state = self.state
        state["instances"][name] = inst
        self.state_path.write_text(json.dumps(state))
        return inst

    def calls(self) -> list[list[str]]:
        log = self.tmp / "calls.log"
        if not log.exists():
            return []
        return [json.loads(line)["argv"] for line in log.read_text().splitlines()]

    def calls_full(self) -> list[dict]:
        log = self.tmp / "calls.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def kali(self, *args: str, input: str = "", **env: str) -> Result:
        e = {**self.env, **env}
        cp = subprocess.run([sys.executable, str(KALI), *args], input=input, text=True, capture_output=True, env=e)
        return Result(cp.returncode, cp.stdout, cp.stderr)


@pytest.fixture
def kenv(tmp_path: Path) -> Env:
    fake = ROOT / "tests" / "fake_incus"
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "PATH": f"{fake}:{os.environ['PATH']}",
        "HOME": str(home),
        "FAKE_INCUS_STATE": str(tmp_path / "state.json"),
        "FAKE_INCUS_LOG": str(tmp_path / "calls.log"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    e = Env(tmp_path, env)
    e.set_state()
    return e

"""incus コマンド呼び出しの唯一の窓口。"""

import json
import os
import subprocess
from collections.abc import Sequence
from typing import Any

from .common import KaliError


class IncusError(KaliError):
    def __init__(self, args: Sequence[str], returncode: int, stderr: str) -> None:
        self.cmd = list(args)
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"incus {' '.join(args[:3])} が失敗しました: {stderr or returncode}")


def run(*args: str, input: str | None = None) -> str:
    """incus を実行し、標準出力を返す。失敗したら IncusError。"""
    cp = subprocess.run(["incus", *args], input=input, text=True, capture_output=True)
    if cp.returncode != 0:
        raise IncusError(args, cp.returncode, cp.stderr.strip())
    return cp.stdout


def try_run(*args: str) -> bool:
    """成否だけを知りたい呼び出し（起動待ちのポーリングなど）。"""
    return subprocess.run(["incus", *args], capture_output=True).returncode == 0


def capture(*args: str) -> tuple[int, str]:
    """終了コードに関わらず標準出力を知りたい呼び出し（systemctl is-system-running など）用。"""
    cp = subprocess.run(["incus", *args], capture_output=True, text=True)
    return cp.returncode, cp.stdout.strip()


def run_visible(*args: str, input: str | None = None) -> None:
    """進捗表示を端末に流したい処理（イメージ取得、apt の導入など）用。"""
    rc = subprocess.run(["incus", *args], input=input, text=True).returncode
    if rc != 0:
        raise IncusError(args, rc, "")


def query(path: str) -> Any:
    return json.loads(run("query", path))


def exec_replace(argv: Sequence[str]) -> None:
    """このプロセスを incus に置き換える。終了コードはそのまま伝わる。"""
    os.execvp("incus", ["incus", *argv])

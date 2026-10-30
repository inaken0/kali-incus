"""kali snapshot / restore。実体は incus snapshot（デバイス設定も含めて保存される）。"""

import re
from datetime import datetime
from urllib.parse import quote

from . import incus
from .common import KaliError, confirm, format_table, info
from .config import Config
from .instance import require

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_RESERVED = ("ls", "rm")  # サブコマンドと衝突する名前


def default_name(now: datetime | None = None) -> str:
    return "snap-" + (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def validate_name(name: str) -> str:
    if not _NAME_RE.match(name) or name in _RESERVED:
        raise KaliError(f"スナップショット名が不正です: {name!r}（英数字と . _ - のみ。ls / rm は使えません）")
    return name


def _names(target: str) -> list[dict[str, str]]:
    snaps = incus.query(f"/1.0/instances/{quote(target)}/snapshots?recursion=1")
    return [{"name": s.get("name", ""), "created": s.get("created_at", "")} for s in snaps]


def _require_snapshot(cfg: Config, name: str) -> None:
    if not any(s["name"] == name for s in _names(cfg.target)):
        raise KaliError(f"スナップショット '{name}' がありません（kali snapshot ls で確認できます）")


def cmd_snapshot(cfg: Config, name: str | None) -> int:
    name = validate_name(name) if name else default_name()
    require(cfg)
    incus.run("snapshot", "create", cfg.target, name)
    info(f"スナップショットを作成しました: {name}")
    return 0


def cmd_snapshot_ls(cfg: Config) -> int:
    require(cfg)
    snaps = _names(cfg.target)
    if not snaps:
        info("スナップショットはありません")
        return 0
    rows = [["NAME", "CREATED"]] + [[s["name"], s["created"]] for s in snaps]
    print(format_table(rows))
    return 0


def cmd_snapshot_rm(cfg: Config, name: str) -> int:
    require(cfg)
    _require_snapshot(cfg, name)
    incus.run("snapshot", "delete", cfg.target, name)
    info(f"スナップショットを削除しました: {name}")
    return 0


def cmd_restore(cfg: Config, name: str, assume_yes: bool) -> int:
    require(cfg)
    _require_snapshot(cfg, name)
    if not confirm(
        f"'{cfg.target}' をスナップショット '{name}' の状態へ戻します。"
        "現在の状態（マウント・ポート公開の設定を含む）は失われます。続けますか?",
        assume_yes,
    ):
        info("中止しました")
        return 1
    incus.run("snapshot", "restore", cfg.target, name)
    info(f"復元しました: {name}")
    return 0

"""kali mount / umount / mount ls。マウントの正本は Incus の disk デバイス。"""

import hashlib
import os
import posixpath
from dataclasses import dataclass

from . import incus
from .common import KaliError, format_table, info
from .config import SOCK_DIR, Config
from .instance import Devices, Instance, require

SHARE_PREFIX = "share-"


@dataclass(frozen=True)
class Mount:
    name: str
    source: str
    path: str
    readonly: bool


def share_name(kali_path: str) -> str:
    """Kali 側パスの sha256 先頭 12 桁からデバイス名を作る。"""
    return SHARE_PREFIX + hashlib.sha256(kali_path.encode()).hexdigest()[:12]


def normalize_kali_path(path: str) -> str:
    """絶対パスのみ受け付け、`realpath -ms` 相当（シンボリックリンクは解決しない）で正規化する。"""
    if not path.startswith("/"):
        raise KaliError(f"Kali 側のパスは絶対パスで指定してください: {path}")
    norm = posixpath.normpath(path)
    if norm.startswith("//"):  # normpath は先頭の // を残す
        norm = "/" + norm.lstrip("/")
    if norm == "/":
        raise KaliError("/ にはマウントできません")
    return norm


def normalize_host_path(path: str) -> str:
    if not os.path.exists(path):
        raise KaliError(f"ホスト側のパスが存在しません: {path}")
    return os.path.realpath(path)


def _is_true(value: str | None) -> bool:
    return (value or "").lower() in ("true", "1", "yes", "on")


def list_mounts(devices: Devices) -> list[Mount]:
    """ツールが内部で使うデバイス（/mnt/.kali-host 配下）とルートを除いた disk デバイス。"""
    mounts = []
    for name, d in devices.items():
        path = d.get("path", "")
        if d.get("type") != "disk" or path in ("", "/"):
            continue
        if path == SOCK_DIR or path.startswith(SOCK_DIR + "/"):
            continue
        mounts.append(Mount(name, d.get("source", ""), path, _is_true(d.get("readonly"))))
    return sorted(mounts, key=lambda m: m.path)


def map_cwd(cwd: str, mounts: list[Mount]) -> str | None:
    """cwd がマウント済みホストパス配下なら Kali 側の対応パスを返す（最長一致）。"""
    best: Mount | None = None
    for m in mounts:
        if not m.source:
            continue
        src = m.source.rstrip("/") or "/"
        inside = cwd == src or cwd.startswith(src.rstrip("/") + "/")
        if inside and (best is None or len(m.source) > len(best.source)):
            best = m
    if best is None:
        return None
    return posixpath.normpath(posixpath.join(best.path, posixpath.relpath(cwd, best.source)))


def missing_sources(devices: Devices) -> list[tuple[str, str]]:
    """起動すると失敗する disk デバイス（ホスト側パスが消えている）を返す。

    ツール内部のデバイスは optional=true で作るので、存在しなくても起動を妨げない。
    """
    return [
        (name, d["source"])
        for name, d in devices.items()
        if d.get("type") == "disk"
        and d.get("source")
        and not _is_true(d.get("optional"))
        and not os.path.exists(d["source"])
    ]


def cmd_mount(cfg: Config, source: str, dest: str, readonly: bool) -> int:
    src = normalize_host_path(source)
    dst = normalize_kali_path(dest)
    inst = require(cfg)
    name = share_name(dst)
    if name in inst.devices:
        raise KaliError(f"{dst} には既にマウントされています（kali mount ls で確認できます）")
    incus.run(
        "config", "device", "add", cfg.target, name, "disk",
        f"source={src}", f"path={dst}", f"readonly={'true' if readonly else 'false'}",
    )  # fmt: skip
    mode = "（読み取り専用）" if readonly else ""
    when = "" if inst.running else "。反映は次回の起動時です"
    info(f"マウントを設定しました: {src} -> {cfg.target}:{dst}{mode}{when}")
    return 0


def cmd_umount(cfg: Config, dest: str) -> int:
    dst = normalize_kali_path(dest)
    inst = require(cfg)
    name = share_name(dst)
    if name not in inst.devices:
        raise KaliError(f"{dst} は kali mount でマウントされたパスではありません（kali mount ls で確認できます）")
    incus.run("config", "device", "remove", cfg.target, name)
    info(f"マウントを解除しました: {dst}")
    return 0


def cmd_mount_ls(cfg: Config) -> int:
    inst: Instance = require(cfg)
    mounts = list_mounts(inst.devices)
    if not mounts:
        info("マウントはありません")
        return 0
    rows = [["KALI_PATH", "HOST_PATH", "MODE"]]
    rows += [[m.path, m.source, "ro" if m.readonly else "rw"] for m in mounts]
    print(format_table(rows))
    return 0

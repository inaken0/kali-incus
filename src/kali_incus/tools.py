"""kali provision: Kali の標準的なツール群とシェル環境を導入する。"""

import re

from . import incus, lifecycle
from .common import KaliError, info
from .config import Config

# インストーラの標準選択（デスクトップ環境を除く）に相当する
DEFAULT_PACKAGES = ["kali-linux-default"]
_PKG_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")


def validate_packages(names: list[str]) -> list[str]:
    for n in names:
        if not _PKG_RE.match(n):
            raise KaliError(f"パッケージ名が不正です: {n!r}")
    return names or list(DEFAULT_PACKAGES)


def cmd_provision(cfg: Config, packages: list[str]) -> int:
    pkgs = validate_packages(packages)
    lifecycle.ensure_running(cfg)
    info(f"導入します: {' '.join(pkgs)}（数 GB のダウンロードになることがあります）")
    incus.run_visible(
        "exec", cfg.target, "-T", "--", "bash", "-s", "--", str(cfg.uid), cfg.user, *pkgs,
        input=lifecycle.script("provision.sh"),
    )  # fmt: skip
    info("完了しました。`kali shell` で確認できます")
    return 0

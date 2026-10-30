"""設定値（環境変数）と target の解決。"""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

from .common import KaliError

DEFAULT_TARGET = "kali"
DEFAULT_IMAGE = "images:kali/current/amd64"

# このツールが管理するコンテナに付けるメタデータ
MANAGED_KEY = "user.kali-incus.managed"
IMAGE_KEY = "user.kali-incus.image"
PROVISIONED_KEY = "user.kali-incus.provisioned"
SSH_AGENT_KEY = "user.kali-incus.ssh-agent"  # "true" のコンテナにホストの ssh-agent を渡す（kali ssh-agent on）

# コンテナ内のプロセスが、同じコンテナ内のプロセスへ signal / ptrace を送れるようにする追加ルール（peer を限定）。
# 新しいカーネル / AppArmor では、次の 2 種類の相手に対する signal と ptrace が拒否される（実機で確認済み）。
#  1. コンテナ自身の積み重ねたプロファイル (…//&unconfined): 拒否されると systemd が起動を完了できない
#  2. ホストのプロファイルがパスで一致して積み重なったもの (例: firefox//&incus-<名前>_…):
#     ホストの Ubuntu の firefox プロファイルは /usr/lib/firefox-esr/firefox-esr にも一致するため、
#     コンテナ内の Firefox が子プロセスへ SIGTERM / SIGKILL を送れず、終了できなくなる
APPARMOR_RAW = (
    "signal peer=incus-**//&unconfined,\n"
    "ptrace peer=incus-**//&unconfined,\n"
    "signal peer=**//&incus-**,\n"
    "ptrace peer=**//&incus-**,"
)

# コンテナ内でホストのソケットを置く場所
SOCK_DIR = "/mnt/.kali-host"

# Incus のインスタンス名: 英数字とハイフンのみ（アンダースコア不可）。先頭は英字、末尾はハイフン不可
_TARGET_RE = re.compile(r"^[A-Za-z]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


@dataclass(frozen=True)
class Config:
    target: str
    image: str
    uid: int
    user: str
    lang: str

    @property
    def is_default_target(self) -> bool:
        return self.target == DEFAULT_TARGET

    def up_hint(self) -> str:
        """「先に作成してください」の案内に使うコマンド。"""
        flag = "" if self.is_default_target else f"-t {self.target} "
        return f"kali {flag}up"


def validate_target(name: str) -> str:
    if not _TARGET_RE.match(name):
        raise KaliError(
            f"target 名が不正です: {name!r}（英字で始まる英数字とハイフンのみ。アンダースコアは使えません）"
        )
    return name


def resolve_target(cli_target: str | None, env: Mapping[str, str]) -> str:
    """優先順位: -t > 環境変数 KALI_TARGET > 既定値。"""
    return validate_target(cli_target or env.get("KALI_TARGET") or DEFAULT_TARGET)


def load(cli_target: str | None, env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    try:
        uid = int(env.get("KALI_UID") or 1000)
    except ValueError:
        raise KaliError(f"KALI_UID が整数ではありません: {env.get('KALI_UID')!r}") from None
    return Config(
        target=resolve_target(cli_target, env),
        image=env.get("KALI_IMAGE") or DEFAULT_IMAGE,
        uid=uid,
        user=env.get("KALI_USER") or "kali",
        lang=env.get("KALI_LANG") or "C.UTF-8",
    )

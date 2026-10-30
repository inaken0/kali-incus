"""kali ssh-agent: ホストの ssh-agent のソケットをコンテナへ渡す。コンテナごとに on / off を選ぶ。

設定は Incus のコンテナ設定 (SSH_AGENT_KEY) に持つ。on のコンテナでは、Wayland と同じように run / shell のたびに
ソケットの inode を比べて、違えば付け直す（ホスト側でエージェントを再起動するとソケットが作り直されるため）。
"""

import os
import stat
from collections.abc import Mapping

from . import incus
from .common import info, warn
from .config import SOCK_DIR, SSH_AGENT_KEY, Config
from .instance import Devices, Instance, require

DEVICE = "ssh-agent"
CONTAINER_SOCK = f"{SOCK_DIR}/ssh-agent"


def host_socket(env: Mapping[str, str]) -> str | None:
    """ホストの SSH_AUTH_SOCK が指す実在のソケット。無ければ None。"""
    path = env.get("SSH_AUTH_SOCK")
    if not path or not os.path.isabs(path):
        return None
    try:
        if not stat.S_ISSOCK(os.stat(path).st_mode):
            return None
    except OSError:
        return None
    return os.path.realpath(path)


def should_forward(inst: Instance, env: Mapping[str, str]) -> bool:
    return inst.ssh_agent and host_socket(env) is not None


def plan_devices(cfg: Config, devices: Devices, env: Mapping[str, str], container_ino: str) -> list[list[str]]:
    """ソケットの inode がコンテナ側と違うときの、デバイスの付け直しに必要な incus 引数。"""
    sock = host_socket(env)
    if sock is None or str(os.stat(sock).st_ino) == container_ino:
        return []
    plan: list[list[str]] = []
    if DEVICE in devices:
        plan.append(["config", "device", "remove", cfg.target, DEVICE])
    plan.append([
        "config", "device", "add", cfg.target, DEVICE, "disk",
        f"source={sock}", f"path={CONTAINER_SOCK}", "optional=true",
    ])  # fmt: skip
    return plan


def cmd_ssh_agent(cfg: Config, mode: str | None) -> int:
    inst = require(cfg)
    if mode is None:
        print(f"ssh-agent の転送: {'有効' if inst.ssh_agent else '無効'}")
        return 0
    if mode == "on":
        incus.run("config", "set", cfg.target, f"{SSH_AGENT_KEY}=true")
        info("ssh-agent の転送を有効にしました。次の kali run / kali shell から SSH_AUTH_SOCK が使えます")
        if host_socket(os.environ) is None:
            warn("いまのシェルの SSH_AUTH_SOCK は、使えるソケットを指していません（エージェントを起動してください）")
        return 0
    incus.run("config", "set", cfg.target, f"{SSH_AGENT_KEY}=false")
    if DEVICE in inst.devices:
        incus.run("config", "device", "remove", cfg.target, DEVICE)
    info("ssh-agent の転送を無効にしました")
    return 0

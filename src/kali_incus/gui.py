"""GUI（Wayland / XWayland）まわり: ソケットの inode 比較、xauth cookie、実行時の環境変数。"""

import os
import subprocess
from collections.abc import Mapping

from .config import SOCK_DIR, Config
from .instance import Devices

X11_DIR = "/tmp/.X11-unix"


def has_gui_session(env: Mapping[str, str]) -> bool:
    return bool(env.get("WAYLAND_DISPLAY") or env.get("DISPLAY"))


def host_wayland_socket(env: Mapping[str, str]) -> str | None:
    disp = env.get("WAYLAND_DISPLAY")
    if not disp:
        return None
    if not disp.startswith("/"):
        runtime = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
        disp = os.path.join(runtime, disp)
    return disp if os.path.exists(disp) else None


def xauth_cookie(display: str) -> str:
    """ホストの cookie のファミリーを wild (ffff) に書き換える（ホスト名の不一致を無視させる）。"""
    try:
        cp = subprocess.run(["xauth", "nlist", display], capture_output=True, text=True)
    except OSError:
        return ""
    if cp.returncode != 0:
        return ""
    return "\n".join("ffff" + line[4:] for line in cp.stdout.splitlines() if len(line) > 4)


def plan_devices(cfg: Config, devices: Devices, env: Mapping[str, str], container_ino: str) -> list[list[str]]:
    """GUI 用デバイスの付け直しに必要な incus 引数のリストを返す。

    Wayland ソケットはファイル単位のバインドなので、ホストで再ログインすると
    コンテナ側は古い inode を指したままになる。inode が違えば付け直す。
    """
    plan: list[list[str]] = []
    sock = host_wayland_socket(env)
    if sock and str(os.stat(sock).st_ino) != container_ino:
        if "wayland" in devices:
            plan.append(["config", "device", "remove", cfg.target, "wayland"])
        plan.append([
            "config", "device", "add", cfg.target, "wayland", "disk",
            f"source={sock}", f"path={SOCK_DIR}/wayland", "optional=true",
        ])  # fmt: skip
    if env.get("DISPLAY") and "x11" not in devices and os.path.isdir(X11_DIR):
        plan.append(x11_device_args(cfg.target))
    return plan


def x11_device_args(target: str) -> list[str]:
    return [
        "config", "device", "add", target, "x11", "disk",
        f"source={X11_DIR}", f"path={SOCK_DIR}/X11-unix", "optional=true",
    ]  # fmt: skip


def runtime_env(
    cfg: Config,
    user: str,
    home: str,
    shell: str,
    has_bus: bool,
    host_env: Mapping[str, str],
    extra: Mapping[str, str] | None = None,
    root: bool = False,
) -> list[str]:
    """`incus exec --env` に渡す KEY=VALUE のリスト。`extra`（`kali run -e`）は既定値より優先する。

    root=True（`kali run --root`）は root として実行する。Wayland のソケットは /run/user/<uid>/ にあるので
    XDG_RUNTIME_DIR は変えず、X11 の cookie はユーザーの ~/.Xauthority を指す。D-Bus のセッションバスは
    ユーザーのもので root は接続できない（uid が違う）ため渡さない。
    """
    env = {
        "HOME": "/root" if root else home, "USER": "root" if root else user,
        "LOGNAME": "root" if root else user, "SHELL": "/bin/bash" if root else shell, "LANG": cfg.lang,
        "TERM": host_env.get("TERM") or "xterm-256color",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "XDG_RUNTIME_DIR": f"/run/user/{cfg.uid}",
    }  # fmt: skip
    if host_env.get("WAYLAND_DISPLAY"):
        env.update({
            "WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "wayland",
            "QT_QPA_PLATFORM": "wayland;xcb", "GDK_BACKEND": "wayland,x11",
            "MOZ_ENABLE_WAYLAND": "1",
            # Qt アプリに GTK のテーマ (Kali-Dark) を使わせる（qt{5,6}-gtk-platformtheme が必要。provision が入れる）。
            # kali-themes が profile.d で指定する qt5ct は、未導入で Qt6 にも効かず、kali run は profile.d を読まない
            "QT_QPA_PLATFORMTHEME": "gtk3",
        })  # fmt: skip
    if host_env.get("DISPLAY"):
        env["DISPLAY"] = host_env["DISPLAY"]
        if root:
            env["XAUTHORITY"] = f"{home}/.Xauthority"
    if host_env.get("COLORTERM"):
        env["COLORTERM"] = host_env["COLORTERM"]
    if has_bus and not root:
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{cfg.uid}/bus"
    env.update(extra or {})
    return [f"{k}={v}" for k, v in env.items()]

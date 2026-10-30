"""前提条件のチェック。不足があれば、利用者が実行すべきコマンドを表示して終了する（sudo は実行しない）。"""

import getpass
import grp
import os
import shutil

from .common import KaliError


# テストで差し替えられるよう、環境変数で上書きできる
def _subid_file(kind: str) -> str:
    return os.environ.get(f"KALI_SUB{kind.upper()}_FILE") or f"/etc/sub{kind}"


def ranges_cover(text: str, name: str, ident: int) -> bool:
    """/etc/subuid 形式のテキストで、`name` に許可された範囲のどれかが `ident` を含むか。"""
    for line in text.splitlines():
        parts = line.strip().split(":")
        if len(parts) != 3 or parts[0] != name:
            continue
        try:
            start, count = int(parts[1]), int(parts[2])
        except ValueError:
            continue
        if start <= ident < start + count:
            return True
    return False


def _read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


def require_incus() -> None:
    if shutil.which("incus") is None:
        raise KaliError("incus が見つかりません。次を実行してから再試行してください:\n"
                        "  sudo apt install incus\n"
                        "  sudo incus admin init --minimal")  # fmt: skip


def check_idmap() -> None:
    """raw.idmap に必要な /etc/subuid, /etc/subgid の設定を確認する（作成時のみ）。"""
    uid, gid = os.getuid(), os.getgid()
    missing = []
    if not ranges_cover(_read(_subid_file("uid")), "root", uid):
        missing.append(f'  echo "root:{uid}:1" | sudo tee -a /etc/subuid')
    if not ranges_cover(_read(_subid_file("gid")), "root", gid):
        missing.append(f'  echo "root:{gid}:1" | sudo tee -a /etc/subgid')
    if missing:
        raise KaliError(
            "UID/GID の対応付け (raw.idmap) に必要な設定がありません。"
            "以下を実行してから再試行してください:\n" + "\n".join(missing) + "\n  sudo systemctl restart incus"
        )


_CONN_ERRORS = ("permission denied", "unix.socket", "cannot connect", "connection refused")


def diagnose(stderr: str) -> str | None:
    """incus が権限や接続で失敗したときの案内文。該当しなければ None。"""
    if not any(k in stderr.lower() for k in _CONN_ERRORS):
        return None
    try:
        group = grp.getgrnam("incus-admin")
    except KeyError:
        return "incus-admin グループがありません。Incus が正しく導入されているか確認してください"
    user = getpass.getuser()
    if group.gr_gid in os.getgroups():
        return "Incus に接続できません。未初期化なら `sudo incus admin init --minimal` を実行してください"
    if user in group.gr_mem:
        return (
            "incus-admin グループには所属していますが、現在のセッションに反映されていません。"
            "一度ログアウトして再ログインしてください（ターミナルを開き直すだけでは反映されません）"
        )
    return (
        "incus-admin グループに所属していません。次を実行し、再ログインしてください:\n"
        f"  sudo usermod -aG incus-admin {user}"
    )

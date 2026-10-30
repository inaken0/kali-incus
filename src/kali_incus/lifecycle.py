"""up / down / reload / destroy / list と、コンテナの作成・起動・初期設定。"""

import os
import time
from importlib import resources

from . import gui, incus, instance, prereq
from .common import KaliError, confirm, format_table, info, warn
from .config import APPARMOR_RAW, IMAGE_KEY, MANAGED_KEY, PROVISIONED_KEY, Config
from .instance import Instance
from .mounts import list_mounts, missing_sources


def script(name: str) -> str:
    return resources.files("kali_incus").joinpath("scripts", name).read_text()


def boot_timeout() -> float:
    """起動完了を待つ最大秒数（テストで短くできるよう環境変数で上書きできる）。"""
    try:
        return float(os.environ.get("KALI_BOOT_TIMEOUT", "90"))
    except ValueError:
        return 90.0


def wait_boot(cfg: Config) -> None:
    """systemd が running / degraded になるまで待つ。

    `systemctl is-system-running --wait` は、起動直後でまだ接続できないと待たずに失敗するため、
    自前で状態を読み続ける。
    """
    deadline = time.monotonic() + boot_timeout()
    while True:
        _, state = incus.capture("exec", cfg.target, "--", "systemctl", "is-system-running")
        if state in ("running", "degraded"):
            return
        if time.monotonic() >= deadline:
            break
        time.sleep(1)
    flag = "" if cfg.is_default_target else f"-t {cfg.target} "
    warn(
        f"コンテナの systemd がまだ起動を完了していません（状態: {state or '不明'}）。\n"
        "処理は続けますが、サービスの起動を伴う操作は固まることがあります。\n"
        "原因の一つは、AppArmor がコンテナ内の systemd の signal / ptrace を拒否することです（Ubuntu 26.04 で確認）。\n"
        "コンテナに AppArmor の許可（raw.apparmor）が無い場合は、次のコマンドで追加し、再起動してください:\n"
        f"  incus config set {cfg.target} raw.apparmor='{APPARMOR_RAW}'\n"
        f"  kali {flag}reload"
    )


NETWORK_EXIT = 42  # setup.sh がネットワーク不通で返す終了コード
_NETWORK_ERRORS = ("Unable to connect", "Failed to fetch", "Could not resolve", "Temporary failure")

NETWORK_HELP = """\
コンテナからインターネットに接続できないため、初期設定を完了できませんでした。
ホスト側のファイアウォールが Incus のブリッジ (incusbr0) の転送を止めている可能性があります。
Docker や ufw を使っている環境で起きやすい問題です。該当する方を実行してから、もう一度
`{up}` を実行してください（コンテナは残してあり、初期設定だけをやり直します）:

  # ufw の場合
  sudo ufw allow in on incusbr0
  sudo ufw route allow in on incusbr0
  sudo ufw route allow out on incusbr0

  # Docker の場合
  sudo iptables -I DOCKER-USER -i incusbr0 -j ACCEPT
  sudo iptables -I DOCKER-USER -o incusbr0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
  sudo ip6tables -I DOCKER-USER -i incusbr0 -j ACCEPT
  sudo ip6tables -I DOCKER-USER -o incusbr0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT

これらは再起動すると消えます。恒久化する systemd ユニットの導入手順は README を参照してください。
"""


def initial_setup(cfg: Config) -> None:
    info("初期設定中（ユーザー作成・必要パッケージの導入）。数分かかることがあります...")
    try:
        incus.run(
            "exec", cfg.target, "-T", "--", "bash", "-s", "--", str(cfg.uid), cfg.user,
            input=script("setup.sh"),
        )  # fmt: skip
    except incus.IncusError as e:
        if e.returncode == NETWORK_EXIT or any(k in e.stderr for k in _NETWORK_ERRORS):
            raise KaliError(NETWORK_HELP.format(up=cfg.up_hint()).rstrip()) from e
        raise
    incus.run("config", "set", cfg.target, f"{PROVISIONED_KEY}=true")


def create(cfg: Config) -> None:
    prereq.check_idmap()
    info(f"コンテナ '{cfg.target}' を作成します ({cfg.image})。初回はイメージの取得に時間がかかります")
    # ホストの UID/GID をコンテナ内の UID/GID に対応付ける（ソケットと共有ファイルの所有者を一致させる）
    idmap = f"uid {os.getuid()} {cfg.uid}\ngid {os.getgid()} {cfg.uid}"
    options = {
        MANAGED_KEY: "true",
        IMAGE_KEY: cfg.image,
        "raw.idmap": idmap,
        "raw.apparmor": APPARMOR_RAW,  # config.APPARMOR_RAW の説明を参照
    }
    incus.run_visible("init", cfg.image, cfg.target, *[a for k, v in options.items() for a in ("-c", f"{k}={v}")])
    if os.path.isdir(gui.X11_DIR):
        incus.run(*gui.x11_device_args(cfg.target))
    if os.path.isdir("/dev/dri"):
        incus.run("config", "device", "add", cfg.target, "gpu", "gpu", "gid=44")


def start(cfg: Config, inst: Instance) -> None:
    missing = missing_sources(inst.devices)
    if missing:
        lines = "\n".join(f"  {src}（デバイス: {name}）" for name, src in missing)
        raise KaliError(
            "マウントしたホスト側のパスが存在しないため、起動しません:\n"
            f"{lines}\n"
            "パスを復元するか、`kali umount` / `kali forward` 系の設定を見直してください"
        )
    info(f"コンテナ '{cfg.target}' を起動します")
    incus.run("start", cfg.target)
    wait_boot(cfg)


def _ensure(cfg: Config, inst: Instance | None) -> Instance:
    if inst is None:
        create(cfg)
        inst = instance.load(cfg.target)
        if inst is None:
            raise KaliError("コンテナの作成後に状態を取得できませんでした")
    instance.check_managed(inst)
    if not inst.running:
        start(cfg, inst)
    if not inst.provisioned:
        initial_setup(cfg)
    if inst.running and inst.provisioned:
        return inst
    return instance.load(cfg.target) or inst


def ensure_running(cfg: Config) -> Instance:
    """作成済みで起動していて初期設定も済んだインスタンスを返す。足りなければ補う。"""
    return _ensure(cfg, instance.load(cfg.target))


def cmd_up(cfg: Config) -> int:
    inst = instance.load(cfg.target)
    if inst is not None and inst.managed and inst.running and inst.provisioned:
        info(f"コンテナ '{cfg.target}' は既に起動しています")
        return 0
    _ensure(cfg, inst)
    info(f"コンテナ '{cfg.target}' の準備ができました")
    return 0


def _stop(cfg: Config, force: bool) -> None:
    incus.run("stop", cfg.target, *(["--force"] if force else []))


def cmd_down(cfg: Config, force: bool) -> int:
    inst = instance.require(cfg)
    if inst.status == "Stopped":
        info(f"コンテナ '{cfg.target}' は既に停止しています")
        return 0
    _stop(cfg, force)
    info(f"コンテナ '{cfg.target}' を停止しました")
    return 0


def cmd_reload(cfg: Config, force: bool) -> int:
    inst = instance.require(cfg)
    if inst.status != "Stopped":
        _stop(cfg, force)
        inst.status = "Stopped"
    _ensure(cfg, inst)
    info(f"コンテナ '{cfg.target}' を再起動しました")
    return 0


def cmd_destroy(cfg: Config, assume_yes: bool, purge_image: bool) -> int:
    inst = instance.require(cfg)
    if not confirm(
        f"コンテナ '{cfg.target}' を削除します。スナップショットも含めて元に戻せません。続けますか?",
        assume_yes,
    ):
        info("中止しました")
        return 1
    fingerprint = inst.config.get("volatile.base_image", "")
    if inst.status != "Stopped":
        _stop(cfg, force=False)
    incus.run("delete", cfg.target)
    info(f"コンテナ '{cfg.target}' を削除しました")
    if purge_image:
        _purge_image(fingerprint)
    return 0


def _purge_image(fingerprint: str) -> None:
    """ほかのコンテナが同じイメージを使っていなければ、キャッシュされたイメージを削除する。"""
    if not fingerprint:
        warn("イメージを特定できなかったため、イメージは削除しません")
        return
    users = [i.name for i in instance.list_all() if i.config.get("volatile.base_image") == fingerprint]
    if users:
        info(f"イメージは {', '.join(users)} が使っているため残します")
        return
    try:
        incus.run("image", "delete", fingerprint)
    except incus.IncusError as e:
        warn(f"イメージの削除に失敗しました: {e.stderr}")
    else:
        info("キャッシュされたイメージを削除しました")


def cmd_list(cfg: Config) -> int:
    insts = instance.list_managed()
    if not insts:
        info("管理しているコンテナはありません。`kali up` で作成できます")
        return 0
    rows = [["", "TARGET", "STATUS", "IMAGE", "MOUNTS"]]
    for i in insts:
        mark = "*" if i.name == cfg.target else ""
        image = i.config.get(IMAGE_KEY, "").removeprefix("images:")
        rows.append([mark, i.name, i.status, image, str(len(list_mounts(i.devices)))])
    print(format_table(rows))
    return 0

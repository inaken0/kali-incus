# CLAUDE.md

Incus 上の Kali Linux コンテナを、コンテナを意識せずに使うための CLI `kali`（Python 3.10+、標準ライブラリのみ）。
ユーザー向けメッセージ・README・コメントは日本語で書く。

## 構成

- `bin/kali` … 薄い起動ラッパー（`../lib/kali-incus` か `../src` を `sys.path` に足す）
- `src/kali_incus/`
  - `cli.py` 引数解析（`-t` はサブコマンドの前のみ）/ `config.py` 環境変数と target 解決
  - `incus.py` **incus 呼び出しの唯一の窓口** / `instance.py` 状態・デバイス取得（query 1 回）、管理判定
  - `prereq.py` 前提チェック / `lifecycle.py` up・down・reload・destroy・list / `run.py` run・shell
  - `mounts.py` `forward.py` `snapshot.py` `tools.py`（provision）`gui.py` `common.py`
  - `scripts/prep.sh`（run のたびに root で実行）, `scripts/setup.sh`（作成直後に 1 回）, `scripts/provision.sh`（`kali provision`）… shellcheck 対象
- `contrib/systemd/` … Docker 併用時のネットワーク対策（`docker-fw.sh` + `kali-incus-docker-fw.service`）。`install.sh` は入れない（root が要るため README の手順で手動導入）
- `tests/` … pytest。`tests/fake_incus/incus` は状態を持つ偽 incus（PATH 先頭に置く）

## 設計判断（変えるときはユーザーと相談）

- target は `-t` > `KALI_TARGET` > `kali`。位置引数は無い。インスタンス名にアンダースコアは使えない。
- **設定・状態ファイルは持たない。** マウント（`share-<sha256 先頭12桁>`）、ポート公開（`fwd-<proto>-<port>`）、スナップショットの正本は Incus。
- 管理対象は `user.kali-incus.managed=true` のコンテナだけ。無ければ全操作を拒否する。`user.kali-incus.provisioned=true` は初期設定完了の印（失敗後の再実行で setup をやり直すため）。
- `mount` / `umount` / `forward` / `snapshot` / `restore` / `reload` は未作成ならエラー（`kali up` を案内）。`run` / `shell` は未作成なら作成する。
- `mount` は停止中でも設定のみ（自動起動しない）。ホスト側パスが消えた disk デバイスがあると `up` は起動せずエラー。ツール内部の x11 / wayland デバイスは `optional=true` なので対象外。
- `run` / `shell` の incus 呼び出しは通常 3 回（query → 準備 exec → 本体 exec）。本体は `os.execvp` で置き換え、終了コードを素通しする。
- `incus exec --user` は補助グループを設定しないので、root で exec して `setpriv --reuid --regid --init-groups` で切り替える。
- Wayland は inode が違えば device を付け直す。GUI セッション（`WAYLAND_DISPLAY` / `DISPLAY`）が無ければ GUI 準備は黙って省略。
- snapshot は自動で取らない（`dir` ドライバでは全コピーで容量を食う）。`restore` はデバイス設定も戻す。
- forward の既定バインドは `127.0.0.1`。ホスト → Kali の方向のみ。
- Docker の `FORWARD DROP` で初期設定が失敗したら、コンテナは残して対処コマンドを案内する（`setup.sh` は終了コード 42）。再実行で初期設定だけやり直す。
- **`kali-defaults` は `useradd` より前に入れる**（`/etc/skel` にある Kali の zsh 設定がユーザー作成時にコピーされるため。順序は test で固定）。既存ユーザーには `provision.sh` が `cp -rn /etc/skel/.` で不足分だけ補う。`provision.sh` は見た目用に `kali-themes` も入れる（`dconf-cli` が付いてくるので dconf のデータベースも作られ、Firefox の dconf 警告が消える）。Kali の GSettings 既定は `adw-gtk3-dark` だがそのパッケージは Kali のリポジトリに無く、存在しないテーマは無視されて Adwaita（明るい）になる（実機で確認）。そのため `/etc/dconf/db/local.d/20-kali-incus-theme` で `Kali-Dark` を指定して `dconf update` する（`adw-gtk3-dark` が実在するなら何もしない）。
- `kali provision` は冪等。既定は `kali-linux-default`、デスクトップ環境は入れない。内部の初期設定完了印 `user.kali-incus.provisioned` は `provision` コマンドとは別物（`lifecycle.initial_setup` が立てる）。
- **新規作成時に `raw.apparmor`（`config.APPARMOR_RAW`）を設定する。** 新しいカーネル / AppArmor では、コンテナ内 systemd の signal / ptrace が拒否され、起動が完了しない（実機で確認: Kali・Debian・`raw.idmap` の有無によらず再現、許可すると約 4 秒で `running`）。peer を限定した 4 行（`incus-**//&unconfined` と `**//&incus-**`、各 signal / ptrace）で、signal / ptrace を丸ごとは許可しない。後者は、ホストの Ubuntu `firefox` プロファイルがパスで一致して積み重なる（`firefox//&incus-<名前>_…`）ため必要。許可がないと Firefox が子へ SIGTERM を送れず終了できない（実機の A/B で確認）。`userns_create` の拒否はホストのセキュリティ機能なので緩めない。既存コンテナは書き換えず、`wait_boot` の警告で手順を示す。ホスト全体の AppArmor には触れない。
- `policy-rc.d` で postinst のサービス起動を止める案は採らなかった（`systemctl` を直接呼ぶ postinst には効かず、通常時にサービス起動を見送る副作用だけが残るため）。
- 起動待ちは `systemctl is-system-running` を 1 秒おきに読んで `running` / `degraded` を待つ。`--wait` は起動直後に接続できないと待たずに失敗するため使わない（実機で確認）。
- `kali run` / `kali shell` は `-e NAME=値` で環境変数を渡せる（コマンドの前に置く。ツールの既定値より優先。`run.split_env_args`）。コンテナ内に `/etc/profile.d` は読み込まれない（ログインシェルを通さない）ので、そこで設定される変数は `-e` で渡す。Wayland セッションのときは、既定で `QT_QPA_PLATFORMTHEME=gtk3` を渡す（Qt アプリが GTK テーマ Kali-Dark を使う。`qt{5,6}-gtk-platformtheme` は provision が入れる。実機で Wireshark を確認）。Java の拡大率は環境ごとに違うので既定に入れない（README にエイリアス等の設定方法）。
- `kali run|shell --root` は `setpriv` を省いて root のまま exec する（incus exec はもともと root）。GUI は `XDG_RUNTIME_DIR=/run/user/<uid>`（Wayland のソケット）と `XAUTHORITY=<ユーザーの home>/.Xauthority`（X11）で使い、`HOME=/root`。ユーザーの D-Bus セッションバスは root から接続できないので渡さない。`sudo` 経由は env_reset で WAYLAND_DISPLAY / XDG_RUNTIME_DIR が消え、X11 にフォールバックして cookie が無く失敗する（実機で確認）。
- フォント: `provision.sh` は `fonts-noto-core` / `fonts-noto-cjk` を入れ、`/etc/fonts/conf.d/69-kali-incus-noto-cjk.conf`（kali-incus 専用なので毎回書き直す）で sans-serif / serif / monospace のフォールバックを Noto (Sans / Serif / Sans Mono) CJK JP→SC→TC→KR にする。zh-cn / zh-tw / zh-hk / ko の lang では対応する地域のフォントを先頭に prepend する（漢字の字形が地域で違うため）。fontconfig 2.17 の既定ではラテン文字は Noto Sans / Noto Serif が先頭（monospace は DejaVu Sans Mono）なので触らない。UI フォント (Cantarell) は変えない。`fc-match` で実機確認済み。
- `provision.sh` の最後で `/etc/systemd/system/run-rpc_pipefs.mount` を `/dev/null` へのリンクで mask する（nfs-common の generator が作るこのマウントは、権限のないコンテナでは permission denied で必ず失敗し、systemd が degraded になるため。実機で確認）。`systemctl daemon-reload` / `reset-failed` は `timeout 30` 付き。
- 既知の問題: `kali provision`（kali-linux-default）直後は systemd が degraded になる。`kali reload` で解消するため修正しない（README の「既知の問題」。`kali-tools-top10` では running のまま。ユーザーの実機で確認）。
- **ssh-agent の転送はコンテナごとの設定**（`kali ssh-agent on|off`、Incus のコンテナ設定 `user.kali-incus.ssh-agent`、既定 off）。on のコンテナでは、`run` / `shell` のたびにホストの `SSH_AUTH_SOCK` が指す実在のソケットを、Wayland と同じく inode 比較で付け直し（デバイス `ssh-agent`、`/mnt/.kali-host/ssh-agent`、`optional=true`）、コンテナ内の `SSH_AUTH_SOCK` を設定する（`-e` が優先）。ホスト側のソケットが無ければ何もしない。`kali mount` でソケットを渡すと、エージェントの再起動後に古い inode を指して使えなくなる（実機で確認）ため作った。デバイスは SOCK_DIR 配下なので `mount ls` には出ない。
- sudo は実行しない。不足があればコマンドを表示して終了する。

## テスト・lint

```sh
pytest                                  # 単体 + 統合（偽 incus）
ruff check . && ruff format --check .
mypy src
shellcheck install.sh completions/kali.bash src/kali_incus/scripts/*.sh contrib/systemd/docker-fw.sh
```

- 統合テストは `bin/kali` をサブプロセスで実行する（`run` は `exec` で置き換わるため）。
- テスト用フック: `KALI_SUBUID_FILE` / `KALI_SUBGID_FILE` で `/etc/subuid` / `/etc/subgid` を差し替える。`KALI_BOOT_TIMEOUT`（秒、既定 90）は systemd の起動待ちの上限。
- 偽 incus が未対応の incus サブコマンドを使うときは `tests/fake_incus/incus` を拡張する。
- 実機でしか確認できない項目は `docs/manual-test.md`。変更したら該当項目も更新する。

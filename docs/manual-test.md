# 実機確認チェックリスト

偽 incus では確認できない項目です。Ubuntu（GNOME / Wayland）に Incus を入れた実機で、上から順に確認します。
テスト用 target を使うと既存環境に影響しません（`kali -t manual-test ...`）。

## 0. 前提チェック

- [ ] `incus` を一時的に PATH から外して `kali list` → 導入コマンドが表示される
- [ ] `incus-admin` に未所属のユーザーで実行 → `usermod` と再ログインの案内が出る
- [ ] `/etc/subuid` から該当行を外して `kali up` → 追記コマンドが表示され、コンテナは作られない

## 1. 作成・起動（up）

- [ ] `kali -t manual-test up` が最後まで通る（初回はイメージ取得に時間がかかる）
- [ ] `incus config get manual-test raw.apparmor` に signal / ptrace の 2 行がある。`kali up` が systemd の警告なしで完了し、`incus exec manual-test -- systemctl is-system-running` が `running`（または `degraded`）
- [ ] カーネルログに、このコンテナ (`incus-manual-test_`) の `apparmor="DENIED"`（signal / ptrace）が出ていない（`sudo journalctl -k | grep DENIED`）
- [ ] `incus config show manual-test` に `user.kali-incus.managed: "true"` と `raw.idmap`（`uid <host> 1000` / `gid <host> 1000`）がある
- [ ] **`raw.idmap` が意図どおり設定されている**（`incus config set ... raw.idmap=...` の改行入り値が受理された）
- [ ] x11 / wayland-less でも `incus config device show manual-test` に x11 と（`/dev/dri` があれば）gpu がある
- [ ] コンテナ内に UID 1000 のユーザー（`kali`）があり、`sudo` / `video` に所属、パスワードなし sudo が効く（`render` には入らないのが正常: このグループは `udev` の導入時に作られ、`kali up` の直後には存在しない。GPU デバイスは `gid=44` (video) で渡すので、`render` への所属は不要）
- [ ] ホストで Docker / ufw が動いていてコンテナの通信が止められている状態で `up` → ファイアウォール設定の案内が出る。案内のコマンドを実行後に `up` を再実行すると、作り直さず初期設定だけが完了する
- [ ] もう一度 `kali -t manual-test up` → 「既に起動しています」で何もしない
- [ ] `kali -t manual-test down` 後の `up` で再び起動する

- [ ] Docker 併用: `sudo systemctl enable --now kali-incus-docker-fw.service` 後、`sudo iptables -S DOCKER-USER` に incusbr0 の ACCEPT が 2 行ある。`systemctl restart docker` 後も 2 行のまま（重複しない）。ホスト再起動後も残る。`systemctl stop docker` で外れる

## 1.5 シェル環境と provision

- [ ] `kali up` 直後に `kali shell` → zsh の新規ユーザー設定ウィザードが出ず、Kali の `┌──(...)` プロンプトで起動する（`~/.zshrc` が `/etc/skel` 由来）
- [ ] zsh の補完候補が薄く出る（autosuggestions）、コマンドが色付けされる（syntax-highlighting）
- [ ] ホストの `$TERM`（kitty / alacritty など）でも `kali shell` が崩れない（`ncurses-term`）
- [ ] `kali provision` で `nmap` / `wireshark` / `msfconsole` が使える。2 回目の実行は短時間で終わる
- [ ] `kali provision` 後、`kali run dconf read /org/gnome/desktop/interface/gtk-theme` が `'Kali-Dark'` を返し、`kali run firefox-esr` と GTK3 のアプリ（zenmap など）が暗いテーマで表示される（目視）。dconf の警告 (`/etc/dconf/db/local`) が出ない
- [ ] `kali provision kali-tools-top10` のように別のメタパッケージを指定できる
- [ ] `kali run wireshark` / `kali run burpsuite` が GNOME にウィンドウで表示される

## 2. 実行（run / shell）

- [ ] `kali -t manual-test run id` → UID 1000、補助グループに sudo (27) / video (44) が含まれる（`render` は含まれなくてよい）。`ls -ln /dev/dri` のグループが 44
- [ ] `kali -t manual-test run sh -c 'exit 7'; echo $?` → `7`
- [ ] `kali -t manual-test shell` で zsh のログインシェルに入れる（`exit` で戻る）
- [ ] 停止中に `kali run true` → 自動で起動する
- [ ] 未作成の target に `kali -t manual-test2 run true` → 作成されて実行される（確認後 destroy）

## 3. GUI

- [ ] Firefox を起動して閉じた後、`kali run pgrep -a firefox` が何も出力しない。`sudo journalctl -k | grep DENIED` に `peer="firefox//&incus-…"` の拒否が出ない（`userns_create` の拒否は想定内）
- [ ] 高解像度ディスプレイで `kali run -e JAVA_ARGS=-Dsun.java2d.uiScale=2 burpsuite` が 200% で表示される（指定なしだと小さい）。`-Dsun.java2d.uiScale=1.5` は無視される。`-Dflatlaf.uiScale=1.5` / `=2` ではフォントが拡大されない（実機で確認済みの制限）
- [ ] `kali run wireshark`（Qt6）が、`-e` なしで GTK のテーマ（Kali-Dark）の暗い表示になる。SSH 経由（GUI セッションなし）では `QT_QPA_PLATFORMTHEME` が渡らない。`-e QT_QPA_PLATFORMTHEME=...` で上書きできる
- [ ] `kali run -e FOO=bar sh -c 'echo $FOO'` が `bar` を表示する。`-e LANG=ja_JP.UTF-8` で `LANG` が上書きされる。`-e` の書式エラーでコンテナ内のコマンドが実行されない
- [ ] `kali run --root zenmap` が起動し、SYN スキャン（`nmap -sS`）が実行できる。`kali run zenmap`（通常ユーザー）では raw ソケットが使えず SYN スキャンは失敗する
- [ ] `kali run --root id -un` が `root`。`kali shell --root` が root の zsh に入る。`/root` 以外（マウント配下）で実行すると作業ディレクトリが対応する Kali 側のパスになる
- [ ] `kali run sudo zenmap` は起動できない（`Authorization required`）。`kali run --root zenmap` は起動できる
- [ ] `kali run fc-match sans-serif` が `Noto Sans`、`kali run fc-match sans-serif:lang=ja` が `Noto Sans CJK JP`。日本語のページ（`kali run firefox-esr`）で、漢字・かなが Noto Sans CJK JP で表示される（Droid Sans Fallback ではない）。メニューやタブの UI は Cantarell のまま
- [ ] 中国語（簡体字）のページで字形が日本語向けではなく中国語向けになる（`fc-match sans-serif:lang=zh-cn` が `Noto Sans CJK SC`）
- [ ] `kali provision` 後、`kali run --root systemctl is-system-running` が `running`（`degraded` ではない）で、`systemctl --failed` が空。`ls -l /etc/systemd/system/run-rpc_pipefs.mount` が `/dev/null` へのリンク
- [ ] `kali -t manual-test run firefox-esr`（要インストール）が **アプリ単位のウィンドウ**として GNOME に表示される
- [ ] XWayland のみのアプリ（例: `xeyes`、`GDK_BACKEND=x11` を指定した GTK アプリ）が表示される
- [ ] ホストで **ログアウト → 再ログイン** した後、`kali run <GUI アプリ>` が再び表示される（inode の付け直し）
- [ ] SSH 経由（`WAYLAND_DISPLAY` なし）で `kali run ls` が普通に動く
- [ ] SSH で作成した後、GUI セッションから `kali run <GUI アプリ>` が `down` / `up` なしで表示される
- [ ] x11 / wayland デバイスの source が存在しない状態（ログアウト中など）で `kali up` が起動できる（`optional=true` が効く）

## 4. マウント

- [ ] `kali -t manual-test mount -s ~/work -d /work` → 稼働中に即時反映、`kali run ls /work` で見える
- [ ] `-r` を付けたマウントは Kali 側から書き込めない
- [ ] `down` → `up` の後もマウントが残っている
- [ ] 停止中に `mount` → 「次回の起動時」と表示され、自動起動しない。`up` 後に反映される
- [ ] マウント元のホストディレクトリを消して `kali up` → 起動せずパスを列挙したエラーになる。`umount` 後は起動できる
- [ ] `~/work/sub` で `kali run pwd` → `/work/sub`。マウント外のディレクトリでは Kali のホーム
- [ ] ホスト側の所有者が Kali 側でも UID 1000 として見え、書き込んだファイルがホスト側で自分の所有になる
- [ ] `kali umount /work` はこのツールが作ったマウントだけを外す（`incus config device add` で手動追加したものは拒否される）

## 4.5 ssh-agent

- [ ] 既定（`kali ssh-agent`）は「無効」。`kali run env | grep SSH_AUTH_SOCK` が何も出さない
- [ ] ホストで Bitwarden（または `ssh-agent`）を起動して `kali ssh-agent on` → `kali run ssh-add -l` がホストの鍵を一覧する
- [ ] ホストでエージェントを終了して再起動（ソケットが作り直される）→ `kali run ssh-add -l` が再び通る（付け直し）
- [ ] 別の target では、設定していなければ渡らない（コンテナごと）
- [ ] `kali ssh-agent off` 後は `SSH_AUTH_SOCK` が渡らず、`incus config device show kali` に `ssh-agent` が無い
- [ ] ホストの `SSH_AUTH_SOCK` が未設定（エージェント終了中）でも `kali up` / `kali run` が失敗しない
- [ ] `kali mount ls` に `ssh-agent` が出ない

## 5. ポート公開

- [ ] コンテナ内で `python3 -m http.server 8000`、ホストで `kali forward 8080 8000` → `curl 127.0.0.1:8080` が通る
- [ ] LAN 側の別端末からは到達できない（既定の `127.0.0.1`）。`--bind 0.0.0.0` を付けると到達できる
- [ ] `down` → `up` の後も転送が残っている。`unforward` で解除できる

## 6. スナップショット

- [ ] `kali snapshot base` → `snapshot ls` に出る。稼働中でも取得できる
- [ ] コンテナ内でファイルを作成 → **稼働中のまま** `kali restore base` → 復元される。結果（実機で確認）: 接続中のコンソール（`kali shell`）は切断され、あとで `kali shell` に入るとスナップショット取得時のファイルの状態になっている
- [ ] `restore` でマウント / ポート公開の設定が取得時点に戻る
- [ ] `kali snapshot rm base` で消える

## 7. 後始末

- [ ] `kali list` に manual-test が出る（現在の target に `*`）
- [ ] `kali -t manual-test destroy` → 確認が出て、`n` / Enter で中止、`y` で削除（稼働中なら停止してから）
- [ ] `--purge-image`: 他のコンテナが同じイメージを使っているときは残り、使っていないときだけ消える（`incus image list`）
- [ ] `kali -t <手動作成した別コンテナ> destroy` は「作成したコンテナではない」と拒否される

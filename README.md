# kali-incus

Ubuntu 上で Kali Linux を Incus のシステムコンテナとして動かし、使うための CLI ラッパー `kali` です。

- systemd が動く Incus のシステムコンテナで Kali を使います。
- GUI アプリはホストの GNOME（Wayland / XWayland）にアプリ単位のウィンドウとして表示されます。
- ホストのディレクトリのマウント、ポート公開、スナップショットを `kali` のコマンドで操作できます。

## 前提

- Ubuntu（GNOME / Wayland）、Python 3.10 以上（標準ライブラリのみ使用）、git
- Incus（次の手順で導入します）

## インストール

### 1. Incus を導入して初期化する

すでに Incus を使っている場合は、手順 2 に進んでください。

```sh
sudo apt install incus
sudo incus admin init --minimal        # ストレージ (dir) とブリッジ (incusbr0) を作る
sudo usermod -aG incus-admin "$USER"   # sudo なしで incus を使えるようにする
```

`incus-admin` グループへの追加は、ログアウトして再ログインすると反映されます。

`kali` はコンテナ内のユーザーとホストのユーザーの UID / GID を対応付けるため（`raw.idmap`）、`/etc/subuid` と `/etc/subgid` に
`root:<自分の UID>:1`（またはそれを含む範囲）が必要です。`id -u` / `id -g` が 1000 でも、Ubuntu の既定では足りないことがあります。確認と追加:

```sh
grep "^root:" /etc/subuid /etc/subgid
echo "root:$(id -u):1" | sudo tee -a /etc/subuid
echo "root:$(id -g):1" | sudo tee -a /etc/subgid
sudo systemctl restart incus
```

不足があれば、`kali` が実行すべきコマンドを表示して終了します。

### 2. kali-incus を導入する

```sh
git clone https://github.com/inaken0/kali-incus.git
cd kali-incus
./install.sh                          # ~/.local へ
sudo ./install.sh PREFIX=/usr/local   # システム全体へ
./install.sh --uninstall              # 削除
```

`PREFIX` 配下の `bin/`、`lib/kali-incus/`、`share/` に配置します（`DESTDIR` も指定できます）。
`~/.local/bin` が `PATH` に入っていることを確認してください。
zsh の補完を `~/.local` で使う場合は、`~/.zshrc` の `compinit` より前に `fpath=(~/.local/share/zsh/site-functions $fpath)` を追加してください（`install.sh` は `~/.zshrc` を書き換えません）。

### 3. 使い始める

```sh
kali up          # 初回はイメージの取得と初期設定で数分かかります
kali provision   # Kali の標準ツールとシェル環境を導入（任意。詳しくは「ツールとシェル環境の導入」）
kali shell
```

## 使い方

```sh
kali up                      # 作成して起動（初回はイメージ取得と初期設定で数分）
kali run firefox-esr         # GUI アプリもそのまま
kali run nmap -sV 10.0.0.1
kali run -e LANG=ja_JP.UTF-8 firefox-esr   # 環境変数を渡す（詳しくは「環境変数を渡す」）
kali run --root zenmap                     # root で実行（詳しくは「root で実行する」）
kali shell                   # Kali のログインシェル（zsh）
kali down                    # 停止
kali destroy                 # 削除（確認あり。-y で省略）
```

target（コンテナ名）は複数持てます。`-t` はコマンドの前に置きます。

```sh
kali -t pentest up
KALI_TARGET=pentest kali shell     # 優先順位: -t > KALI_TARGET > 既定値 "kali"
kali list                          # 管理しているコンテナ（現在の target に * が付く）
```

### 環境変数を渡す（`-e`）

```sh
kali run -e JAVA_ARGS=-Dsun.java2d.uiScale=2 burpsuite
kali run -e QT_QPA_PLATFORMTHEME=gtk3 -e QT_QPA_PLATFORM=xcb wireshark
kali shell -e FOO=bar
```

- `-e NAME=値`（または `--env NAME=値`、`--env=NAME=値`）を、コマンドの前に何個でも置けます。最初に `-e` 以外が現れた所からが、コンテナ内で実行するコマンドです（`--` で区切れば、`-e` で始まるコマンドも実行できます）。
- 値には `=` や空白を含められます（`-e A=b=c d`）。
- ツールが既定で設定する環境変数（`LANG`、`QT_QPA_PLATFORM` など）は、`-e` で上書きできます。

### root で実行する（`--root`）

```sh
kali run --root zenmap          # nmap の SYN スキャンなど、root が必要な GUI アプリ
kali run --root nmap -sS 10.0.0.1
kali shell --root               # root のログインシェル
```

- 通常のユーザーは raw ソケットを開けないため（`Operation not permitted`）、`nmap -sS` などは root が必要です。`--root` を付けると、ユーザーへの切り替えをせず、root として実行します。
- GUI アプリも使えます。Wayland のソケット（`/run/user/<uid>/`）と、X11 の cookie（ユーザーの `~/.Xauthority`）を使うように環境変数を設定します。`HOME` は `/root` になります。
- ユーザーの D-Bus のセッションバスは root から接続できないため、渡しません。
- `-e` と組み合わせられます（`kali run --root -e FOO=bar cmd`）。オプションはコマンドの前に置きます。
- コンテナの root は、ホストでは権限のないユーザーに対応します（ユーザー名前空間）。

> `kali run sudo zenmap` は `Authorization required` で失敗します。`sudo` が環境変数を消すためです。root で実行するには `--root` を使ってください。

### ツールとシェル環境の導入（provision）

```sh
kali provision                          # kali-linux-default（インストーラの標準選択からデスクトップ環境を除いたもの）
kali provision kali-tools-top10         # 好きなメタパッケージを指定（複数可）
```

`kali up` で作られるコンテナは最小構成です。`kali provision` を実行すると、Kali をインストールした直後と同じ使い心地になります。

- **ツール**: 指定したメタパッケージ（省略時は `kali-linux-default`）を導入します。数 GB のダウンロードになることがあります。
- **シェル環境**: Kali 標準の zsh 設定（`kali-defaults` の `/etc/skel`）と、zsh-autosuggestions / zsh-syntax-highlighting を導入します。
- **フォント**: `fonts-noto-core` と `fonts-noto-cjk`（日本語・中国語・韓国語）を導入し、fontconfig の設定（`/etc/fonts/conf.d/69-kali-incus-noto-cjk.conf`）で、日本語などのフォールバックを Noto CJK にします。既定は日本語（Noto Sans CJK JP）で、中国語・韓国語のページでは地域に合った字形（SC / TC / HK / KR）を選びます。ダウンロードは約 65 MB です。Firefox は起動し直すと反映されます。
- **見た目**: `kali-themes`（テーマ・アイコン・フォント）を導入します。GTK テーマは `/etc/dconf/db/local.d/20-kali-incus-theme` で `Kali-Dark` / `Flat-Remix-Blue-Dark` に指定します（Kali の既定の `adw-gtk3-dark` は Kali のリポジトリに無いため）。ユーザー自身の設定（`dconf write` や `~/.config/gtk-3.0/settings.ini`）が優先されます。ウィンドウの枠やタイトルバーはホストの GNOME が描くため、変わりません。
- **NFS**: `nfs-common` が作る `run-rpc_pipefs.mount` は、コンテナ内ではマウントに失敗して `systemctl status` が `degraded` になるため、`mask` します。
- 何度実行しても構いません。すでにあるユーザーの設定ファイルは上書きせず、足りないものだけ補います。
- 未作成の target なら、`run` と同じように作成してから導入します。
- デスクトップ環境は入れません。
- `dir` ストレージでは、導入後にスナップショットを取ると、その分の容量も使います。

### マウント（永続）

```sh
kali mount -s ~/work -d /work       # ホスト → Kali（-r で読み取り専用）
kali mount ls
kali umount /work
```

- 停止中でも設定でき、次の起動から有効です。
- ホスト側のパスが消えていると、`kali up` はエラーで起動しません。`kali umount` で外してください。
- `kali run` / `kali shell` は、ホストのカレントディレクトリがマウント済みパス配下なら、Kali 側の対応パスで開始します（複数該当は最長一致）。それ以外は Kali のホームです。

### ssh-agent をコンテナで使う

```sh
kali ssh-agent on       # このコンテナにホストの ssh-agent を渡す
kali ssh-agent          # 現在の状態（有効 / 無効）を表示
kali ssh-agent off      # 渡さない
```

- 設定は **コンテナごと**で、既定は無効です。`-t` で別の target にも設定できます（`kali -t pentest ssh-agent on`）。
- 有効にすると、`kali run` / `kali shell` のたびに、ホストの `SSH_AUTH_SOCK` が指すソケットをコンテナへ渡し、コンテナ内の `SSH_AUTH_SOCK` を設定します。Bitwarden、`ssh-agent`、`gpg-agent` など、ソケットを `SSH_AUTH_SOCK` で公開するものならどれでも使えます。
- ホストでエージェントを再起動してソケットが作り直されても、次の `kali run` / `kali shell` で付け直します。
- ホストの `SSH_AUTH_SOCK` が未設定、またはソケットが存在しないときは、何も渡しません。
- コンテナ内のプログラムは、エージェントに登録されたすべての鍵で署名を求められます（鍵そのものは渡りません）。信頼できるコンテナにだけ有効にしてください。
- 実行中のプロセスの環境変数は変わらないため、`kali ssh-agent on` の後は `kali shell` を開き直してください。
- `kali run -e SSH_AUTH_SOCK=...` で、渡す値を上書きできます。

### ポート公開

```sh
kali forward 8080 80                        # ホストの 127.0.0.1:8080 → Kali の 80
kali forward 4444 4444 --bind 0.0.0.0       # LAN へ公開するとき
kali forward ls
kali unforward 8080
```

ホスト → Kali の方向のみです（Incus の proxy デバイス）。既定の待ち受けアドレスは `127.0.0.1` です。

### スナップショット

```sh
kali snapshot base           # 名前を省略すると snap-日時
kali snapshot ls
kali restore base            # 確認あり。-y で省略
kali snapshot rm base
```

- スナップショットにはデバイス設定も含まれます。`restore` すると、マウントやポート公開の設定も取得時点に戻ります。
- 稼働中でも `restore` できます。接続中の `kali shell` などは**切断され**、コンテナの内容はスナップショットを取った時点に巻き戻ります。
- `dir` ストレージでは、スナップショットはルートファイルシステムの全コピーです。1 つ取るごとに同じだけ容量を使います。

## 設定（環境変数）

| 変数 | 既定値 | 意味 |
|---|---|---|
| `KALI_TARGET` | `kali` | 対象のコンテナ名（英数字とハイフン） |
| `KALI_IMAGE` | `images:kali/current/amd64` | 作成時のイメージ |
| `KALI_UID` | `1000` | コンテナ内ユーザーの UID（作成時のみ有効） |
| `KALI_USER` | `kali` | コンテナ内ユーザー名（作成時のみ有効） |
| `KALI_LANG` | `C.UTF-8` | 実行時の `LANG` |

## GUI について

- Wayland ソケットは `/mnt/.kali-host/wayland` にマウントされます。ホストで再ログインしても、`run` / `shell` のたびに inode を比べて付け直します。
- GUI セッションがない（SSH など）ときは、GUI の準備を省きます。後から GUI セッションで `kali run` すれば、`down` / `up` なしで使えます。すでに起動済みのプロセスは GUI につながらないため、起動し直してください。
- コンテナ内の systemd ユーザーサービスには、Wayland 関連の環境変数は渡りません。

### 見た目と表示サイズ

- **GTK アプリ**（Firefox、zenmap など）は、`kali provision` で Kali の暗いテーマ（`Kali-Dark`）になります。設定の詳細は「ツールとシェル環境の導入」を参照してください。
- **Qt アプリ**（Wireshark など）は、`kali run` が環境変数 `QT_QPA_PLATFORMTHEME=gtk3` を渡すため、GTK のテーマ（`Kali-Dark`）で表示されます。これには `qt5-gtk-platformtheme` / `qt6-gtk-platformtheme` が必要で、`kali provision` が入れます。GUI セッションがないときは渡しません。別のテーマにしたい場合は `-e QT_QPA_PLATFORMTHEME=...` で上書きできます。
- Burp Suite など Java (Swing) のアプリは、高解像度ディスプレイで小さく表示されます。XWayland の X11 アプリは自動で拡大されず、Java も拡大率を検出できないためです。JVM に拡大率を渡してください。

  ```sh
  kali run -e JAVA_ARGS=-Dsun.java2d.uiScale=2 burpsuite
  ```

  - `JAVA_ARGS` は、Kali の Java ラッパー (`java-wrappers`) が JVM のオプションとして渡す環境変数です。
  - 指定できるのは整数だけです。`-Dsun.java2d.uiScale=1.5` は無視されます（Java 25 の X11）。150% などの表示は、現状ではできません。
  - 拡大するとフォントのアンチエイリアスの見え方が変わることがあります。

#### Java の拡大率を、自分の環境の既定にする

Java の拡大率は、ディスプレイや GNOME の設定によって変わるため、`kali run` の既定の環境変数には入れていません。ホスト側のシェルやランチャーに、自分の環境の値を書いておきます。

- **シェルのエイリアス**（`~/.zshrc` や `~/.bashrc`）:

  ```sh
  alias burp='kali run -e JAVA_ARGS=-Dsun.java2d.uiScale=2 burpsuite'
  ```

- **モニターごとに値が違う**ときは、変数にしておくと切り替えられます。

  ```sh
  export KALI_JAVA_SCALE=2          # 例: 外付けの 5K は 2、ノート PC は 1
  alias burp='kali run -e JAVA_ARGS=-Dsun.java2d.uiScale=${KALI_JAVA_SCALE:-1} burpsuite'
  ```

- **スクリプト**にする場合（`~/.local/bin/burp`、実行権限を付ける）:

  ```sh
  #!/bin/sh
  exec kali run -e "JAVA_ARGS=-Dsun.java2d.uiScale=${KALI_JAVA_SCALE:-2}" burpsuite "$@"
  ```

`JAVA_ARGS` が影響するのは Java のアプリだけです。他の Java アプリ（Ghidra など）にも同じ指定が使えます。

## Docker と併用する場合（ネットワーク設定）

ホストで Docker が動いていると、Docker が `iptables` の `FORWARD` の既定ポリシーを `DROP` にします。
そのままでは Incus のブリッジ (`incusbr0`) の通信も捨てられ、コンテナが外に出られません
（`kali up` の初期設定で `Unable to connect to kali.download` となります）。
Docker が用意している `DOCKER-USER` チェーンに許可ルールを足すと解決します。

### 一時的に試す（再起動すると消える）

```sh
sudo iptables -I DOCKER-USER -i incusbr0 -j ACCEPT
sudo iptables -I DOCKER-USER -o incusbr0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
```

### 恒久化する（systemd ユニット）

Docker の起動に合わせてルールを自動投入するユニットを `contrib/systemd/` に用意しています。
`install.sh` は root 権限が要るこの設定を行いません。リポジトリの直下で、次を実行してください。

```sh
sudo install -D -m 0755 contrib/systemd/docker-fw.sh /usr/local/libexec/kali-incus/docker-fw.sh
sudo install -D -m 0644 contrib/systemd/kali-incus-docker-fw.service \
    /etc/systemd/system/kali-incus-docker-fw.service
sudo systemctl daemon-reload
sudo systemctl enable --now kali-incus-docker-fw.service
```

確認:

```sh
systemctl status kali-incus-docker-fw.service     # active (exited)
sudo iptables -S DOCKER-USER                       # incusbr0 の ACCEPT が 2 行ある
```

- ユニットは `docker.service` に紐づいています。Docker の起動・再起動のたびにルールを入れ直し、Docker を止めると外します。
  ルールは重ねて追加されません（何度実行しても同じ結果になります）。
- IPv6 は、Docker が `ip6tables` を使っている（`DOCKER-USER` が `ip6tables` にもある）場合だけ設定します。
- ブリッジ名が `incusbr0` 以外のときは、`sudo systemctl edit kali-incus-docker-fw.service` で上書きします。

  ```ini
  [Service]
  Environment=KALI_BRIDGE=your-bridge
  ```

- 削除:

  ```sh
  sudo systemctl disable --now kali-incus-docker-fw.service
  sudo rm /etc/systemd/system/kali-incus-docker-fw.service /usr/local/libexec/kali-incus/docker-fw.sh
  sudo systemctl daemon-reload
  ```

ufw を使っている環境では、代わりに次を実行します。

```sh
sudo ufw allow in on incusbr0
sudo ufw route allow in on incusbr0
sudo ufw route allow out on incusbr0
```

初期設定の途中で失敗した場合も、コンテナは残っています。ネットワークを直したあとに `kali up` を再実行すると、初期設定だけがやり直されます。

## AppArmor の追加ルールについて

新しいカーネルと AppArmor の組み合わせ（検証したのはカーネル 7.0.0-42 / Incus 6.0.5）では、コンテナ内の systemd の `signal` / `ptrace` が AppArmor に拒否され、コンテナの起動処理が完了しません（`systemctl is-system-running` が `initializing` のまま止まり、`apt` が固まります）。

そのため `kali up` は、新規に作るコンテナの `raw.apparmor` に次の 4 行を設定します。

```
signal peer=incus-**//&unconfined,
ptrace peer=incus-**//&unconfined,
signal peer=**//&incus-**,
ptrace peer=**//&incus-**,
```

- 前半の 2 行は、systemd が起動を完了するために必要です。
- 後半の 2 行は、ホストの AppArmor プロファイル（Ubuntu 標準の `firefox` など）がコンテナ内の同じパスのプロセスにも一致して積み重なるときのためのものです。ないと Firefox が子プロセスに `SIGTERM` を送れず、終了できません。
- 許可する相手（peer）は Incus のコンテナのプロファイルを持つプロセスに限られ、そのコンテナのプロファイルにだけ適用されます。`kali destroy` でプロファイルごと消えます。
- Incus やカーネルの更新でこの問題が直れば、不要になります。

ホストの `kernel.apparmor_restrict_unprivileged_userns=1` による、コンテナ内のユーザー名前空間の作成 (`userns_create`) の拒否は緩めません。Firefox や `bwrap` は、サンドボックスが弱まった状態で動くことがあります。

すでにあるコンテナ（このツールを使わずに作ったものなど）には設定しません。`kali up` / `kali run` で `systemd がまだ起動を完了していません` と警告されたら、表示されるコマンドで追加し、再起動してください（`kali` の部分はコンテナ名です）。

```sh
incus config set kali raw.apparmor='signal peer=incus-**//&unconfined,
ptrace peer=incus-**//&unconfined,
signal peer=**//&incus-**,
ptrace peer=**//&incus-**,'
kali reload
```

## トラブルシューティング

- **`kali up` の初期設定で `Unable to connect to kali.download` と出る**: 上の「Docker と併用する場合」を参照してください。
- **`systemd がまだ起動を完了していません` と警告される**: 上の「AppArmor の追加ルールについて」を参照してください。
- **incus-admin に所属しているのに権限エラーになる**: 一度ログアウトして再ログインしてください。

## 既知の問題

- **`kali provision` の直後は `systemctl status` が `degraded` になる**: 失敗したユニットが残るためです（原因は特定していません）。
  `kali reload` で再起動すると解消し、`running` になります。動作に支障はないため、現時点では対処していません。`kali provision kali-tools-top10` のように
  小さいメタパッケージでは `running` のままです。失敗したユニットは `kali run --root systemctl --failed` で確認できます。

## 開発

```sh
python3 -m venv .venv && .venv/bin/pip install pytest ruff mypy shellcheck-py
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy src
.venv/bin/shellcheck install.sh completions/kali.bash src/kali_incus/scripts/*.sh contrib/systemd/docker-fw.sh
```

実機での確認手順は [docs/manual-test.md](docs/manual-test.md) を参照してください。

## 今後の拡張（未対応）

- Wi-Fi の monitor mode（物理 NIC のパススルー）
- 音声（PipeWire）の転送
- Kali → ホスト方向のポート転送
- GUI アプリのホスト側ランチャーへの登録（エクスポート）

## ライセンス

[MIT License](LICENSE)

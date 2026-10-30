#!/bin/bash
# kali provision: Kali の標準的なツールとシェル環境を導入する。冪等。
#   引数: $1=ユーザーの UID  $2=ユーザー名  $3...=導入するメタパッケージ
set -eu
uid=$1
name=$2
shift 2

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq

# シェル環境: Kali 標準の zsh 設定（kali-defaults の /etc/skel）とプラグイン
# 見た目: kali-themes（GTK のテーマ・アイコン・フォント。dconf-cli も入り、dconf のデータベースが作られる）
# qt{5,6}-gtk-platformtheme: Qt アプリ (Wireshark など) が GTK のテーマを使うためのプラグイン（kali run が QT_QPA_PLATFORMTHEME=gtk3 を渡す）
# フォント: Noto（fonts-noto-core）と Noto CJK（日本語・中国語・韓国語）。UI のフォント (Cantarell) は変えない
apt-get install -y -qq kali-defaults zsh-autosuggestions zsh-syntax-highlighting ncurses-term \
  kali-themes qt5-gtk-platformtheme qt6-gtk-platformtheme fonts-noto-core fonts-noto-cjk >/dev/null

# fontconfig: 既定のままだと日本語は Droid Sans Fallback になる。ラテン文字の後ろのフォールバックを Noto CJK にする。
# ラテン文字のフォント自体は fontconfig 既定の優先順位（Noto Sans / Noto Serif が先頭）に任せる。このファイルは kali-incus 専用なので毎回書き直す
cat >/etc/fonts/conf.d/69-kali-incus-noto-cjk.conf <<'EOT'
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
  <!-- kali-incus: ラテン文字のフォントに無い文字（日本語など）のフォールバックを Noto CJK にする。
       既定は日本語 (JP)。中国語・韓国語のページでは、地域に合った字形を先に選ぶ -->
  <alias>
    <family>sans-serif</family>
    <prefer>
      <family>Noto Sans CJK JP</family>
      <family>Noto Sans CJK SC</family>
      <family>Noto Sans CJK TC</family>
      <family>Noto Sans CJK KR</family>
    </prefer>
  </alias>
  <alias>
    <family>serif</family>
    <prefer>
      <family>Noto Serif CJK JP</family>
      <family>Noto Serif CJK SC</family>
      <family>Noto Serif CJK TC</family>
      <family>Noto Serif CJK KR</family>
    </prefer>
  </alias>
  <alias>
    <family>monospace</family>
    <prefer>
      <family>Noto Sans Mono CJK JP</family>
      <family>Noto Sans Mono CJK SC</family>
      <family>Noto Sans Mono CJK TC</family>
      <family>Noto Sans Mono CJK KR</family>
    </prefer>
  </alias>
  <match target="pattern">
    <test name="lang" compare="contains"><string>zh-cn</string></test>
    <test name="family"><string>sans-serif</string></test>
    <edit name="family" mode="prepend" binding="same"><string>Noto Sans CJK SC</string></edit>
  </match>
  <match target="pattern">
    <test name="lang" compare="contains"><string>zh-cn</string></test>
    <test name="family"><string>serif</string></test>
    <edit name="family" mode="prepend" binding="same"><string>Noto Serif CJK SC</string></edit>
  </match>
  <match target="pattern">
    <test name="lang" compare="contains"><string>zh-cn</string></test>
    <test name="family"><string>monospace</string></test>
    <edit name="family" mode="prepend" binding="same"><string>Noto Sans Mono CJK SC</string></edit>
  </match>
  <match target="pattern">
    <test name="lang" compare="contains"><string>zh-tw</string></test>
    <test name="family"><string>sans-serif</string></test>
    <edit name="family" mode="prepend" binding="same"><string>Noto Sans CJK TC</string></edit>
  </match>
  <match target="pattern">
    <test name="lang" compare="contains"><string>zh-tw</string></test>
    <test name="family"><string>serif</string></test>
    <edit name="family" mode="prepend" binding="same"><string>Noto Serif CJK TC</string></edit>
  </match>
  <match target="pattern">
    <test name="lang" compare="contains"><string>zh-tw</string></test>
    <test name="family"><string>monospace</string></test>
    <edit name="family" mode="prepend" binding="same"><string>Noto Sans Mono CJK TC</string></edit>
  </match>
  <match target="pattern">
    <test name="lang" compare="contains"><string>zh-hk</string></test>
    <test name="family"><string>sans-serif</string></test>
    <edit name="family" mode="prepend" binding="same"><string>Noto Sans CJK HK</string></edit>
  </match>
  <match target="pattern">
    <test name="lang" compare="contains"><string>zh-hk</string></test>
    <test name="family"><string>serif</string></test>
    <edit name="family" mode="prepend" binding="same"><string>Noto Serif CJK HK</string></edit>
  </match>
  <match target="pattern">
    <test name="lang" compare="contains"><string>zh-hk</string></test>
    <test name="family"><string>monospace</string></test>
    <edit name="family" mode="prepend" binding="same"><string>Noto Sans Mono CJK HK</string></edit>
  </match>
  <match target="pattern">
    <test name="lang" compare="contains"><string>ko</string></test>
    <test name="family"><string>sans-serif</string></test>
    <edit name="family" mode="prepend" binding="same"><string>Noto Sans CJK KR</string></edit>
  </match>
  <match target="pattern">
    <test name="lang" compare="contains"><string>ko</string></test>
    <test name="family"><string>serif</string></test>
    <edit name="family" mode="prepend" binding="same"><string>Noto Serif CJK KR</string></edit>
  </match>
  <match target="pattern">
    <test name="lang" compare="contains"><string>ko</string></test>
    <test name="family"><string>monospace</string></test>
    <edit name="family" mode="prepend" binding="same"><string>Noto Sans Mono CJK KR</string></edit>
  </match>
</fontconfig>
EOT

# GTK3 / GTK4 のテーマ: kali-themes が設定するのは GTK2 (/etc/gtk-2.0/gtkrc) と Qt だけで、GTK3/4 は各デスクトップ環境が
# 選ぶ作りになっている。デスクトップ環境が無いので、システム全体の settings.ini で指定する。
# ファイルが無いときだけ作る（既存の設定は上書きしない。ユーザーの ~/.config が優先される）
for v in 3.0 4.0; do
  f=/etc/xdg/gtk-$v/settings.ini
  if [ ! -e "$f" ]; then
    install -d "/etc/xdg/gtk-$v"
    printf '[Settings]\ngtk-theme-name=Kali-Dark\ngtk-icon-theme-name=Flat-Remix-Blue-Dark\n' >"$f"
  fi
done

# GTK のテーマ: kali-themes の GSettings 既定は adw-gtk3-dark だが、そのパッケージ (adw-gtk3) は Kali のリポジトリに無く、
# コンテナには入らない。存在しないテーマは無視されて Adwaita（明るい）になるため、dconf のシステム設定で実在する
# Kali-Dark を指定する（dconf のシステム設定は gschema.override の既定値より優先され、ユーザーの設定はさらに優先される）。
# adw-gtk3-dark が実在するなら（将来リポジトリに入ったなら）何もしない。ファイルが無いときだけ作る
f=/etc/dconf/db/local.d/20-kali-incus-theme
if [ ! -d /usr/share/themes/adw-gtk3-dark ] && [ ! -e "$f" ] && command -v dconf >/dev/null; then
  install -d /etc/dconf/db/local.d
  cat >"$f" <<'EOT'
[org/gnome/desktop/interface]
gtk-theme='Kali-Dark'
icon-theme='Flat-Remix-Blue-Dark'
color-scheme='prefer-dark'
EOT
  dconf update
fi

pw=$(getent passwd "$uid") || { echo "UID $uid のユーザー ($name) がいません" >&2; exit 1; }
IFS=: read -r user _ _ _ _ home _ <<<"$pw"

# 先に作られていたユーザーには /etc/skel が配られていない。足りないものだけ補う（上書きしない）
runuser -u "$user" -- cp -rn /etc/skel/. "$home"/ 2>/dev/null || true

# 利用者が選んだツール群（進捗は端末へそのまま流れる）
apt-get install -y "$@"

# nfs-common（kali-linux-default）の rpc-pipefs-generator が run-rpc_pipefs.mount を生成するが、権限のないコンテナでは
# rpc_pipefs をマウントできず（permission denied）、毎回 failed になって systemd が degraded になる。
# showmount など NFS を調べるコマンドには不要なので mask する（/etc/systemd/system は generator の出力より優先される。
# `systemctl mask` と同じ /dev/null へのリンク。systemctl が固まっても進めるよう、後始末は上限時間付き）
ln -sf /dev/null /etc/systemd/system/run-rpc_pipefs.mount
timeout 30 systemctl daemon-reload 2>/dev/null || true
timeout 30 systemctl reset-failed run-rpc_pipefs.mount 2>/dev/null || true

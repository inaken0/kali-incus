#!/bin/bash
# コンテナ内で run / shell のたびに root で実行する準備スクリプト。
#   引数: $1=ユーザーの UID  $2=ホストのソケットを置いたディレクトリ
#   標準入力: ホストから受け取った X11 cookie（空でもよい）
#   標準出力: key=value 形式（ユーザー情報、Wayland / ssh-agent ソケットの inode など）
set -u
uid=$1
sockdir=$2

pw=$(getent passwd "$uid") || { echo nouser=1; exit 0; }
IFS=: read -r user _ _ gid _ home shell <<<"$pw"

# /run/user/<uid> と Wayland ソケットへのシンボリックリンク
rt=/run/user/$uid
[ -d "$rt" ] || install -d -m 0700 -o "$uid" -g "$gid" "$rt"
ln -sfn "$sockdir/wayland" "$rt/wayland-0"

# XWayland: /tmp は起動後にマウントされる tmpfs なので、直接マウントせずリンクで対応する
if [ -d "$sockdir/X11-unix" ]; then
  echo x11=1
  install -d -m 1777 /tmp/.X11-unix
  for s in "$sockdir"/X11-unix/X*; do
    [ -S "$s" ] && ln -sfn "$s" "/tmp/.X11-unix/${s##*/}"
  done
fi

# X11 cookie の取り込み
cookie=$(cat)
if [ -n "$cookie" ] && command -v xauth >/dev/null; then
  printf '%s\n' "$cookie" | xauth -f "$home/.Xauthority" nmerge - 2>/dev/null || true
  chown "$uid:$gid" "$home/.Xauthority" 2>/dev/null || true
fi

[ -S "$rt/bus" ] && echo bus=1
echo "ino=$(stat -Lc %i "$sockdir/wayland" 2>/dev/null || true)"
echo "ssh_ino=$(stat -Lc %i "$sockdir/ssh-agent" 2>/dev/null || true)"
printf 'user=%s\ngid=%s\nhome=%s\nshell=%s\n' "$user" "$gid" "$home" "$shell"
exit 0

# kali の bash 補完
_kali() {
  local cur=${COMP_WORDS[COMP_CWORD]} prev=${COMP_WORDS[COMP_CWORD-1]}
  local cmds="up down reload destroy list provision run shell mount umount ssh-agent forward unforward snapshot restore help"
  local i=1 sub=""
  while (( i < COMP_CWORD )); do
    case ${COMP_WORDS[i]} in
      -t|--target) i=$((i + 2)); continue ;;
      -*) ;;
      *) sub=${COMP_WORDS[i]}; break ;;
    esac
    i=$((i + 1))
  done

  if [[ $prev == -t || $prev == --target ]]; then
    local targets
    targets=$(kali list 2>/dev/null | awk 'NR>1 { print ($1 == "*") ? $2 : $1 }')
    mapfile -t COMPREPLY < <(compgen -W "$targets" -- "$cur")
    return
  fi
  if [[ -z $sub ]]; then
    mapfile -t COMPREPLY < <(compgen -W "$cmds -t --target -h --version" -- "$cur")
    return
  fi
  case $sub in
    down|reload)  mapfile -t COMPREPLY < <(compgen -W "-f --force" -- "$cur") ;;
    destroy)      mapfile -t COMPREPLY < <(compgen -W "-y --yes --purge-image" -- "$cur") ;;
    restore)      mapfile -t COMPREPLY < <(compgen -W "-y --yes" -- "$cur") ;;
    mount)
      if [[ $prev == -s || $prev == --source ]]; then
        mapfile -t COMPREPLY < <(compgen -f -- "$cur")
      else
        mapfile -t COMPREPLY < <(compgen -W "ls -s --source -d --dest -r --readonly" -- "$cur")
      fi ;;
    forward)      mapfile -t COMPREPLY < <(compgen -W "ls --proto --bind" -- "$cur") ;;
    unforward)    mapfile -t COMPREPLY < <(compgen -W "--proto" -- "$cur") ;;
    ssh-agent)    mapfile -t COMPREPLY < <(compgen -W "on off" -- "$cur") ;;
    snapshot)     mapfile -t COMPREPLY < <(compgen -W "ls rm" -- "$cur") ;;
    provision)    mapfile -t COMPREPLY < <(compgen -W "kali-linux-default kali-linux-headless kali-linux-large kali-tools-top10 kali-tools-web kali-tools-wireless" -- "$cur") ;;
    run|shell)
      if [[ $cur == -* ]]; then
        mapfile -t COMPREPLY < <(compgen -W "--root -e --env" -- "$cur")
      elif [[ $sub == run ]]; then
        mapfile -t COMPREPLY < <(compgen -c -- "$cur")
      fi ;;
  esac
}
complete -F _kali kali

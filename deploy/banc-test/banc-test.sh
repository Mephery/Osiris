#!/usr/bin/env bash
# Banc de test VM locale : valide la chaine PXE/WinPE sans materiel.
# Voir deploy/banc-test/README.md.
#
#   banc-test.sh reseau     cree le pont et l'interface tap (a refaire au reboot)
#   banc-test.sh demarrer   cree le disque au besoin, lance la VM
#   banc-test.sh etat       ce qui tourne, ce qui existe
#   banc-test.sh arreter    arrete la VM proprement
#   banc-test.sh nettoyer   supprime pont, tap et fichiers de la VM
set -euo pipefail

PONT=${PONT:-br-test}
TAP=${TAP:-tap-test}
# Adresse de l'hote sur le reseau du banc. Doit correspondre a la conf dnsmasq
# et ne surtout pas empieter sur le VLAN de deploiement.
ADRESSE=${ADRESSE:-10.0.1.1/24}

MAC=${MAC:-52:54:00:51:21:15}
SERIE=${SERIE:-VMTESTWINPE01}
MEMOIRE=${MEMOIRE:-4096}
COEURS=${COEURS:-2}
TAILLE_DISQUE=${TAILLE_DISQUE:-60G}
# 1 = QEMU ecrit dans un fichier temporaire detruit a l'arret. Le disque ne
# grossit jamais : c'est le bon mode pour un simple test d'amorcage.
DISQUE_JETABLE=${DISQUE_JETABLE:-0}

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRAVAIL=${TRAVAIL:-$ICI/vm}
DISQUE="$TRAVAIL/disk.qcow2"
MONITEUR="$TRAVAIL/monitor.sock"
NVRAM="$TRAVAIL/OVMF_VARS.fd"
ISO=${ISO:-$TRAVAIL/osiris-winpe.iso}

OVMF_CODE=/usr/share/OVMF/OVMF_CODE_4M.fd
OVMF_VARS=/usr/share/OVMF/OVMF_VARS_4M.fd

pid_vm() { pgrep -f "serial=$SERIE" || true; }

reseau() {
    # Chaque etape est conditionnelle : relancer la commande apres un reboot
    # partiel ne doit pas echouer sur ce qui existe deja.
    ip link show "$PONT" >/dev/null 2>&1 || sudo ip link add name "$PONT" type bridge
    ip -br addr show "$PONT" | grep -q "${ADRESSE%%/*}" || sudo ip addr add "$ADRESSE" dev "$PONT"
    sudo ip link set "$PONT" up
    ip link show "$TAP" >/dev/null 2>&1 || sudo ip tuntap add dev "$TAP" mode tap user "$USER"
    sudo ip link set "$TAP" master "$PONT"
    sudo ip link set "$TAP" up
    echo "pont $PONT ($ADRESSE) et interface $TAP prets"
}

demarrer() {
    [ -n "$(pid_vm)" ] && { echo "la VM tourne deja (PID $(pid_vm))"; return 0; }
    ip link show "$TAP" >/dev/null 2>&1 || { echo "reseau absent : lancer '$0 reseau'" >&2; exit 1; }
    mkdir -p "$TRAVAIL"
    [ -f "$DISQUE" ] || qemu-img create -f qcow2 "$DISQUE" "$TAILLE_DISQUE"
    # Les variables UEFI sont propres a la VM : partir de la copie du systeme.
    [ -f "$NVRAM" ] || cp "$OVMF_VARS" "$NVRAM"
    [ -f "$ISO" ] || { echo "ISO introuvable : $ISO" >&2; exit 1; }

    local jetable=()
    [ "$DISQUE_JETABLE" = "1" ] && jetable=(-snapshot)

    # SATA (ahci/ide-hd) et e1000 sont imposes par WinPE, qui n'a pas virtio.
    sg kvm -c "qemu-system-x86_64 -machine q35,accel=kvm -cpu host \
        -smp $COEURS -m $MEMOIRE -smbios type=1,serial=$SERIE ${jetable[*]} \
        -drive if=pflash,format=raw,unit=0,readonly=on,file=$OVMF_CODE \
        -drive if=pflash,format=raw,unit=1,file=$NVRAM \
        -drive file=$DISQUE,format=qcow2,if=none,id=hd0 \
        -device ahci,id=ahci -device ide-hd,drive=hd0,bus=ahci.0,bootindex=2 \
        -cdrom $ISO -boot order=d \
        -netdev tap,id=n0,ifname=$TAP,script=no,downscript=no \
        -device e1000,netdev=n0,mac=$MAC,bootindex=1 \
        -monitor unix:$MONITEUR,server,nowait -display none -vga std &"
    sleep 1
    echo "VM lancee (PID $(pid_vm)) — penser a '$0 arreter' en fin de session"
}

arreter() {
    local pid; pid=$(pid_vm)
    [ -z "$pid" ] && { echo "aucune VM en cours"; return 0; }
    kill -TERM $pid
    for _ in $(seq 1 10); do kill -0 $pid 2>/dev/null || break; sleep 1; done
    kill -0 $pid 2>/dev/null && { echo "arret force"; kill -KILL $pid; }
    rm -f "$MONITEUR"
    echo "VM arretee"
}

etat() {
    local pid; pid=$(pid_vm)
    echo "VM      : ${pid:-arretee}"
    [ -n "$pid" ] && echo "  CPU cumule : $(ps -o time= -p $pid | tr -d ' ')"
    echo "pont    : $(ip -br addr show "$PONT" 2>/dev/null || echo absent)"
    echo "tap     : $(ip -br link show "$TAP" 2>/dev/null || echo absent)"
    [ -f "$DISQUE" ] && echo "disque  : $(du -h "$DISQUE" | cut -f1) ($DISQUE)"
}

nettoyer() {
    arreter
    sudo ip link del "$TAP" 2>/dev/null || true
    sudo ip link del "$PONT" 2>/dev/null || true
    rm -rf "$TRAVAIL"
    echo "pont, interface et fichiers de la VM supprimes"
}

case "${1:-}" in
    reseau)   reseau ;;
    demarrer) demarrer ;;
    arreter)  arreter ;;
    etat)     etat ;;
    nettoyer) nettoyer ;;
    *) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//' ; exit 1 ;;
esac

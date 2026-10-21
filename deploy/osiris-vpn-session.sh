#!/bin/bash
# Installé en root:root 0700 dans /usr/local/sbin/osiris-vpn-session.sh
# Invoqué par backend/vpn.py via `sudo -n` (voir deploy/osiris-vpn.sudoers).
#   osiris-vpn-session.sh <slug> stop            ferme la session (conf conservée)
#   osiris-vpn-session.sh <slug> expire <sec>    (ré)arme la fermeture dans <sec> secondes
#
# L'échéance est une minuterie systemd transitoire, et non un simple calcul côté
# OSIRIS : elle ferme le tunnel même si l'API est arrêtée ou plantée. Transitoire,
# elle disparaît au redémarrage — le tunnel n'étant plus `enable`, il ne remonte pas.
set -euo pipefail

SLUG="${1:?slug requis}"
ACTION="${2:?action requise (stop|expire)}"

if ! [[ "$SLUG" =~ ^[a-z0-9][a-z0-9-]{0,30}$ ]]; then
    echo "slug invalide: $SLUG" >&2
    exit 1
fi

MINUTERIE="osiris-vpn-expire-${SLUG}"

desarmer() {
    systemctl stop "${MINUTERIE}.timer" "${MINUTERIE}.service" 2>/dev/null || true
    systemctl reset-failed "${MINUTERIE}.timer" "${MINUTERIE}.service" 2>/dev/null || true
}

case "$ACTION" in
    stop)
        desarmer
        systemctl stop "openvpn-client@${SLUG}"
        ;;
    expire)
        SECONDES="${3:?durée en secondes requise}"
        if ! [[ "$SECONDES" =~ ^[0-9]{1,6}$ ]] || (( SECONDES < 60 )); then
            echo "durée invalide: $SECONDES" >&2
            exit 1
        fi
        desarmer
        systemd-run --quiet --unit="$MINUTERIE" --on-active="${SECONDES}s" \
            --timer-property=AccuracySec=10s \
            /usr/bin/systemctl stop "openvpn-client@${SLUG}"
        ;;
    *)
        echo "action inconnue: $ACTION" >&2
        exit 1
        ;;
esac

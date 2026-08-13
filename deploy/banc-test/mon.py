#!/usr/bin/env python3
"""Client du moniteur QEMU : envoie une commande, et sait prendre une capture.

WinPE n'a aucune sortie exploitable : pas de console serie, pas de journal
accessible depuis l'hote. La seule facon de savoir ou en est l'amorcage est de
regarder l'ecran — ce que `screendump` permet sans VNC ni affichage.

    mon.py shot ecran.png     capture l'ecran (PPM converti en PNG)
    mon.py info status        n'importe quelle commande du moniteur

Le socket est cherche a cote de ce script (vm/monitor.sock), ou dans la variable
d'environnement MONITEUR.
"""

import os
import socket
import sys
import time

ICI = os.path.dirname(os.path.abspath(__file__))
SOCK = os.environ.get("MONITEUR", os.path.join(ICI, "vm", "monitor.sock"))


def cmd(commande: str, attente: float = 0.6) -> str:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCK)
    time.sleep(0.3)
    try:
        s.recv(65536)          # banniere d'accueil du moniteur
    except OSError:
        pass
    s.sendall((commande + "\n").encode())
    time.sleep(attente)
    sortie = b""
    s.setblocking(False)
    try:
        while True:
            morceau = s.recv(65536)
            if not morceau:
                break
            sortie += morceau
    except BlockingIOError:
        pass
    s.close()
    return sortie.decode(errors="replace")


def shot(chemin_png: str) -> str:
    """screendump ecrit un PPM de facon asynchrone : il faut attendre que le
    fichier existe ET soit non vide, sinon on convertit un fichier tronque."""
    ppm = chemin_png.replace(".png", ".ppm")
    if os.path.exists(ppm):
        os.unlink(ppm)
    cmd(f"screendump {ppm}", attente=1.5)
    for _ in range(20):
        if os.path.exists(ppm) and os.path.getsize(ppm) > 0:
            break
        time.sleep(0.3)
    from PIL import Image
    image = Image.open(ppm)
    image.save(chemin_png)
    os.unlink(ppm)
    return f"{chemin_png} ({image.width}x{image.height})"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    if not os.path.exists(SOCK):
        sys.exit(f"socket moniteur introuvable : {SOCK} — la VM tourne-t-elle ?")
    if sys.argv[1] == "shot":
        print(shot(sys.argv[2]))
    else:
        print(cmd(" ".join(sys.argv[1:])))

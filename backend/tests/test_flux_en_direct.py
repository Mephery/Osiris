# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Le flux en direct (/ws/machines) exige un jeton, et diffuse vraiment.

Il était ouvert à quiconque atteignait OSIRIS, alors qu'il diffuse les MAC et
les journaux de déploiement — et qu'une MAC suffit à réclamer les scripts d'une
machine en cours d'installation. Le jeton arrive en premier message : un
navigateur ne pose pas d'en-tête sur un WebSocket.

Au passage : les résultats des smoke tests n'y arrivaient jamais (appel de
`broadcast` à deux arguments, TypeError avalé en silence).
"""
import pytest
from sqlmodel import Session
from starlette.websockets import WebSocketDisconnect

from models import Machine, engine

MAC = "aabbccddee20"


def _machine():
    with Session(engine) as s:
        s.add(Machine(mac=MAC, hostname="PC-20", client="c", os="ubuntu", status="deploying"))
        s.commit()


# Chaque test déclenche un message témoin APRÈS l'action testée : si l'action
# n'a rien diffusé, c'est le témoin qui arrive en premier et le test échoue —
# au lieu d'attendre indéfiniment un message qui ne viendra pas.

def test_sans_jeton_la_connexion_est_fermee(client, clean_db):
    _machine()
    with client.websocket_connect("/ws/machines") as ws:
        ws.send_text("pas-un-jeton")
        client.post(f"/machines/{MAC}/log", params={"msg": "témoin"})
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_text()
    assert e.value.code == 4401


def test_avec_un_jeton_les_evenements_arrivent(client, admin_token, clean_db):
    _machine()
    with client.websocket_connect("/ws/machines") as ws:
        ws.send_text(admin_token)
        client.post(f"/machines/{MAC}/log", params={"msg": "bonjour"})
        assert ws.receive_json()["mac"] == MAC


def test_les_resultats_des_smoke_tests_arrivent_en_direct(client, admin_token, clean_db):
    _machine()
    with client.websocket_connect("/ws/machines") as ws:
        ws.send_text(admin_token)
        client.post(f"/machines/{MAC}/smoke-tests", json={"tests": [{"name": "SSH", "ok": True}]})
        client.post(f"/machines/{MAC}/log", params={"msg": "témoin"})
        msg = ws.receive_json()
    assert msg.get("type") == "smoke", f"premier message reçu : {msg}"
    assert msg["mac"] == MAC
    # Surtout pas sous la clé « status » : l'interface la prendrait pour le statut de la machine
    assert "status" not in msg and msg["smoke_status"]

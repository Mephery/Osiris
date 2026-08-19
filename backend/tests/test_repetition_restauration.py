# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Ce que la répétition de restauration doit garantir, dans le script livré.

Une sauvegarde ne vaut que par sa restauration, et rien dans la suite de tests ne
peut restaurer une vraie archive : le script tourne en root, lit un volume en
`600` et crée des bases PostgreSQL. Ces contrôles lisent donc le fichier livré et
verrouillent les quelques propriétés dont la disparition serait *silencieuse* —
celles qui laisseraient la répétition continuer à s'afficher en vert tout en ne
prouvant plus rien.
"""
from pathlib import Path

import pytest

DEPOT = Path(__file__).resolve().parents[2]
SCRIPT = DEPOT / "deploy" / "backup" / "osiris-backup.sh"


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_la_restauration_sarrete_a_la_premiere_erreur(script):
    """Sans `--exit-on-error`, une restauration à moitié faite passe pour un succès.

    C'est le piège central de `pg_restore` : par défaut il signale ses erreurs sur
    la sortie d'erreur et sort quand même en 0. Une répétition qui perdrait ce
    drapeau continuerait à afficher « réussie » sur une archive dont la moitié des
    tables manquent — exactement le mensonge qu'elle est censée dissiper.
    """
    assert "pg_restore --exit-on-error" in script, \
        "la repetition doit echouer des la premiere erreur de restauration"


def test_la_repetition_refuse_de_viser_la_base_de_production(script):
    """La répétition détruit sa base : elle ne doit jamais pouvoir viser la vraie.

    `dropdb` puis `createdb` sur `$BASE` effacerait toute l'installation. Le
    garde-fou est bon marché, et son absence ne se verrait qu'une seule fois.
    """
    assert '[ "$REPETITION_BASE" = "$BASE" ]' in script, \
        "la repetition doit refuser de tourner si sa base jetable est celle de production"


def test_le_nettoyage_survit_a_la_fin_de_la_fonction(script):
    """Le trap EXIT s'exécute après la disparition des variables locales.

    Constaté en écrivant la répétition : le trap portait `rm -rf "$tmp"` avec un
    `tmp` déclaré `local`. À l'EXIT, la fonction était rendue, la variable
    n'existait plus, et `set -u` faisait échouer le nettoyage — le script sortait
    en 1 *après* avoir tout réussi, et surtout laissait derrière lui une base
    jetable pleine de vraies données. Le nettoyage passe donc par une fonction et
    des variables globales.
    """
    assert "trap nettoyer_repetition EXIT" in script, \
        "le nettoyage doit etre une fonction, pas une commande citant des locales"

    debut = script.index("nettoyer_repetition() {")
    corps = script[debut:script.index("\n}", debut)]
    assert "dropdb --if-exists" in corps, \
        "le nettoyage doit detruire la base jetable, y compris quand un controle echoue"
    assert "REPETITION_TMP" in corps and "local " not in corps, \
        "le nettoyage ne peut lire que des variables globales"


def test_la_coherence_de_la_cle_est_controlee(script):
    """Une archive restaurable dont la clé ne l'ouvre pas est une archive perdue.

    Le dump et la `FERNET_KEY` voyagent ensemble mais viennent de deux sources
    différentes. Si elles cessent de correspondre, la restauration reste
    impeccable et *tous* les secrets deviennent illisibles — jonction AD, PIN
    BitLocker, jetons d'hyperviseur. Ce contrôle est le seul à voir cette panne.
    """
    assert "FERNET_KEY=" in script and "Fernet(" in script, \
        "la repetition doit dechiffrer un secret avec la cle de la meme archive"
    assert 'decrypt(os.environ["JETON"]' in script, \
        "le dechiffrement doit porter sur un vrai secret tire de la base restauree"


def test_le_clair_dechiffre_nest_jamais_affiche(script):
    """Le contrôle prouve que la clé ouvre le secret ; il n'a pas à le montrer.

    Le journal de la répétition part dans systemd, donc dans Zabbix. Y déverser un
    mot de passe d'hyperviseur en clair transformerait un contrôle de sauvegarde
    en fuite de secrets.
    """
    debut = script.index('FERNET_KEY="$cle"')
    fin = script.index("journal", debut)
    assert "print(" not in script[debut:fin], \
        "le secret dechiffre ne doit jamais etre imprime"


def test_les_unites_de_la_repetition_sont_livrees():
    """Le contrôle doit tourner tout seul : un mode qu'on lance à la main s'oublie."""
    service = (SCRIPT.parent / "osiris-repetition.service").read_text(encoding="utf-8")
    minuteur = (SCRIPT.parent / "osiris-repetition.timer").read_text(encoding="utf-8")

    assert "--repetition" in service, "le service doit lancer le mode repetition"
    assert "OnCalendar=" in minuteur, "le minuteur doit avoir une echeance"
    # Une machine eteinte le dimanche ne doit pas sauter son tour en silence.
    assert "Persistent=true" in minuteur, \
        "un passage manque doit etre rattrape, pas oublie"


def test_lechec_de_la_repetition_est_visible_dans_zabbix():
    """Un contrôle dont personne ne lit le résultat ne contrôle rien.

    Le troisième paramètre de la clé est indispensable : `Result` appartient à
    l'interface `Service`, pas à `Unit`. Sans lui, l'item reste indéfiniment en
    ZBX_NOTSUPPORTED — donc muet, comme s'il n'existait pas.
    """
    modele = (DEPOT / "deploy" / "supervision"
              / "zabbix-template-osiris-server.yaml").read_text(encoding="utf-8")

    assert 'systemd.unit.info["osiris-repetition.service","Result","Service"]' in modele, \
        "le resultat de la repetition doit etre releve par le modele Zabbix"

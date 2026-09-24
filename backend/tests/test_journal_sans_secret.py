# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Le journal de déploiement Windows ne doit porter aucun secret.

`Write-Log` écrit la ligne en local ET l'envoie à OSIRIS, qui la conserve en
base (`deploy_log_line`) et la rend exportable en .txt depuis la fiche. Le PIN
BitLocker y figurait en clair (« PIN : 482913 ») alors qu'il est rangé chiffré
juste à côté — constaté le 24/09 en relisant la branche TPM+PIN.

Le test porte sur l'invariant — aucune ligne journalisée n'interpole une
variable qui contient un secret — plutôt que sur la seule ligne corrigée.
"""
import re

SECRETS = ("$pin", "$securePin", "$existingKey", "$newPassword", "$lapsPassword",
           "$biosPwd", "$securePassword", "$djPwdPlain")


def test_aucune_ligne_journalisee_ne_contient_de_secret():
    source = open("templates/firstboot-windows.ps1.j2", encoding="utf-8").read()
    fuites = []
    for numero, ligne in enumerate(source.splitlines(), 1):
        if "Write-Log" not in ligne:
            continue
        for secret in SECRETS:
            # Frontière de mot : `$pin` ne doit pas attraper `$ping`.
            if re.search(re.escape(secret) + r"(?![A-Za-z0-9_])", ligne):
                fuites.append(f"ligne {numero} : {secret} — {ligne.strip()}")
    assert not fuites, "secret envoyé au journal :\n" + "\n".join(fuites)

# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
from sqlmodel import Session, select
from models import Machine, engine, init_db

def seed_data():
    # 1. On s'assure que la table existe
    print("[OSIRIS] Création des tables...")
    init_db()
    
    # 2. On ouvre une session de travail avec la BDD
    with Session(engine) as session:
        
        # On vérifie si la base est déjà remplie pour éviter les doublons
        statement = select(Machine)
        existing_machines = session.exec(statement).all()
        
        if len(existing_machines) > 0:
            print("[OSIRIS] La base de données contient déjà des machines. Abandon du seeding.")
            return

        print("[OSIRIS] Injection des machines de test...")
        
        # On crée nos objets Python "Machine"
        machine1 = Machine(
            mac="001a2b3c4d5e",
            client="Client_Bidule",
            os="windows",
            hostname="PC-COMPTA-04",
            ou="OU=Compta,OU=Computers,DC=bidule,DC=local"
        )
        
        machine2 = Machine(
            mac="001a2b3c4d9f",
            client="Client_Chouette",
            os="ubuntu",
            hostname="SRV-WEB-02",
            ou="OU=Serveurs,DC=chouette,DC=local"
        )
        
        # On les prépare pour la BDD et on valide la transaction
        session.add(machine1)
        session.add(machine2)
        session.commit()
        print("[OSIRIS] Base de données initialisée et synchronisée avec succès")

if __name__ == "__main__":
    seed_data()
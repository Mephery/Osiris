// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { useEffect, useState } from 'react'
import type { InventaireVm } from './types'
import { authHeader } from './types'
import { lireReponse } from './api'
import { Spinner } from './Skeleton'
import { filtrerInventaire, reseauxInventaire } from './inventaire'

const API_URL = import.meta.env.VITE_API_URL ?? ''

/** Ce qui tourne déjà sur un hyperviseur : VM, réseaux, adresses. LECTURE SEULE.
 *
 *  OSIRIS ne voyait que ses propres fiches ; tout le reste, les VM posées à la
 *  main, n'existait pour lui que comme une adresse prise en silence. Ici on voit
 *  tout — et on ne peut rien y modifier ni supprimer : ce n'est pas à OSIRIS de
 *  toucher aux machines qu'il n'a pas créées. */
export function InventaireHyperviseur({ token, hvId }: { token: string; hvId: number }) {
  const [vms, setVms] = useState<InventaireVm[] | null>(null)
  const [erreur, setErreur] = useState('')
  const [reseau, setReseau] = useState('')
  const [texte, setTexte] = useState('')

  useEffect(() => {
    let actif = true
    fetch(`${API_URL}/hypervisors/${hvId}/inventory`, { headers: authHeader(token) })
      .then(r => lireReponse<InventaireVm[]>(r, "Lecture de l'inventaire refusée"))
      .then(v => { if (actif) setVms(v) })
      .catch((e: Error) => { if (actif) setErreur(e.message) })
    return () => { actif = false }
  }, [token, hvId])

  if (erreur) return <p className="text-[10px] text-red-400">⛔ {erreur}</p>
  if (!vms) return (
    <p className="text-[10px] text-slate-500 flex items-center gap-2">
      <Spinner /> Lecture de toutes les VM de l'hyperviseur… quelques secondes.
    </p>
  )

  const reseaux = reseauxInventaire(vms)
  const affichees = filtrerInventaire(vms, reseau, texte)
  const ipsConnues = vms.reduce((n, v) => n + v.cartes.reduce((m, c) => m + c.ips.length, 0), 0)

  return (
    <div className="space-y-2">
      <p className="text-[10px] text-slate-500">
        {vms.length} VM · {ipsConnues} adresses connues · {vms.filter(v => v.osiris).length} créées par OSIRIS
        <span className="text-slate-600"> — lecture seule : rien ici ne modifie l'hyperviseur.</span>
      </p>
      <div className="flex gap-2">
        <select value={reseau} onChange={e => setReseau(e.target.value)} className="osiris-input text-xs">
          <option value="">Tous les réseaux</option>
          {reseaux.map(r => <option key={r.reseau} value={r.reseau}>{r.reseau} ({r.vms} VM)</option>)}
        </select>
        <input value={texte} onChange={e => setTexte(e.target.value)} placeholder="Chercher un nom ou une adresse"
          className="osiris-input text-xs flex-1 min-w-0" />
      </div>
      <div className="max-h-96 overflow-y-auto">
        <table className="w-full text-[11px]">
          <thead className="sticky top-0 bg-slate-950">
            <tr className="text-slate-500 text-left">
              <th className="font-normal pr-3 py-1">VM</th>
              <th className="font-normal pr-3">Nœud</th>
              <th className="font-normal pr-3">Réseau</th>
              <th className="font-normal">Adresses</th>
            </tr>
          </thead>
          <tbody>
            {affichees.map(vm => (
              <tr key={`${vm.vmid}-${vm.nom}`} className="border-t border-slate-800/50 align-top">
                <td className="pr-3 py-1">
                  <span className={vm.etat === 'allumee' ? 'text-slate-200' : 'text-slate-500'}>{vm.nom}</span>
                  {vm.etat === 'eteinte' && <span className="text-slate-600"> · éteinte</span>}
                  {vm.genre === 'conteneur' && <span className="text-slate-600"> · conteneur</span>}
                  {vm.osiris && <span className="ml-1.5 border border-blue-800/60 text-blue-400 rounded px-1 text-[9px]" title={`Fiche OSIRIS : ${vm.osiris}`}>OSIRIS</span>}
                </td>
                <td className="pr-3 font-mono text-slate-500">{vm.noeud}</td>
                <td className="pr-3 font-mono text-slate-400">
                  {vm.cartes.map((c, i) => <div key={i}>{c.reseau || '—'}</div>)}
                </td>
                <td className="font-mono">
                  {vm.cartes.map((c, i) => (
                    <div key={i}>
                      {c.ips.length === 0 ? <span className="text-slate-600">inconnue</span> : c.ips.map((a, j) => (
                        <span key={a.ip} className={a.source === 'agent' ? 'text-slate-300' : 'text-slate-500'}
                          title={a.source === 'agent' ? 'Lue dans la VM (agent invité)' : 'Déclarée dans la configuration'}>
                          {j > 0 && ', '}{a.ip}
                        </span>
                      ))}
                    </div>
                  ))}
                </td>
              </tr>
            ))}
            {affichees.length === 0 && (
              <tr><td colSpan={4} className="text-slate-600 py-2">Aucune VM ne correspond.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

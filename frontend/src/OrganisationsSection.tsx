// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { useState } from 'react'
import { toast } from 'sonner'
import type { Organization, OrganizationPatch } from './types'
import { authHeader } from './types'
import { IcoPencil } from './icons'
import { lireReponse } from './api'
import { brouillonDe, changementsOrg, slugDepuisNom, type BrouillonOrg } from './orgForm'

const API_URL = import.meta.env.VITE_API_URL ?? ''

/** Administration → Organisations.
 *
 *  L'ancien écran alignait quatre champs ouverts par organisation, enregistrés
 *  en quittant le champ : on modifiait sans le vouloir, on ne savait pas si
 *  c'était parti, et la croix de suppression voisinait avec le nom. Ici chaque
 *  organisation se lit en une ligne ; le crayon ouvre la modification, qui
 *  s'enregistre explicitement ; la suppression est dans la modification, et
 *  confirmée. La création vit à part, à droite : on ne confond plus « ce qui
 *  existe » et « ce que j'ajoute ». */
export function OrganisationsSection({ token, orgs, onChange }: {
  token: string
  orgs: Organization[]
  onChange: () => void
}) {
  const [enEdition, setEnEdition] = useState<number | null>(null)
  const [brouillon, setBrouillon] = useState<BrouillonOrg | null>(null)
  const [nouveauNom, setNouveauNom]   = useState('')
  const [nouveauSlug, setNouveauSlug] = useState('')
  // Le slug suit le nom tant qu'on ne l'a pas retouché soi-même
  const [slugTouche, setSlugTouche]   = useState(false)
  const [envoi, setEnvoi] = useState(false)

  const ouvrir = (o: Organization) => { setEnEdition(o.id); setBrouillon(brouillonDe(o)) }
  const fermer = () => { setEnEdition(null); setBrouillon(null) }

  const enregistrer = (o: Organization) => {
    if (!brouillon) return
    const patch: OrganizationPatch = changementsOrg(o, brouillon)
    if (Object.keys(patch).length === 0) { fermer(); return }
    setEnvoi(true)
    fetch(`${API_URL}/organizations/${o.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...authHeader(token) },
      body: JSON.stringify(patch),
    })
      .then(r => lireReponse(r, 'Enregistrement refusé'))
      .then(() => { toast.success(`${patch.name ?? o.name} enregistrée`); fermer(); onChange() })
      .catch((e: Error) => toast.error(e.message))
      .finally(() => setEnvoi(false))
  }

  const supprimer = (o: Organization) => {
    if (!window.confirm(`Supprimer définitivement l'organisation « ${o.name} » ?`)) return
    fetch(`${API_URL}/organizations/${o.id}`, { method: 'DELETE', headers: authHeader(token) })
      .then(r => lireReponse(r, 'Suppression refusée'))
      .then(() => { toast.success(`${o.name} supprimée`); fermer(); onChange() })
      .catch((e: Error) => toast.error(e.message, { duration: 10000 }))
  }

  const creer = (e: React.FormEvent) => {
    e.preventDefault()
    setEnvoi(true)
    fetch(`${API_URL}/organizations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(token) },
      body: JSON.stringify({ name: nouveauNom.trim(), slug: nouveauSlug }),
    })
      .then(r => lireReponse<Organization>(r, 'Création refusée'))
      .then((o: Organization) => {
        toast.success(`${o.name} créée`)
        setNouveauNom(''); setNouveauSlug(''); setSlugTouche(false)
        onChange()
        // Une organisation neuve n'a encore rien : on ouvre sa fiche pour la régler
        ouvrir(o)
      })
      .catch((e: Error) => toast.error(e.message))
      .finally(() => setEnvoi(false))
  }

  const titre = 'text-xs font-bold uppercase tracking-widest text-slate-500'
  const etiquette = 'block text-[10px] text-slate-500 space-y-0.5'

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_300px] items-start">

      {/* ── Ce qui existe ───────────────────────────────────────────────── */}
      <div className="osiris-table-wrap p-5 space-y-3">
        <h2 className={titre}>Organisations existantes ({orgs.length})</h2>
        <ul className="space-y-2">
          {orgs.map(o => enEdition === o.id && brouillon ? (
            <li key={o.id} className="border border-blue-500/40 rounded p-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-widest text-blue-300">Modification</span>
                <span className="font-mono text-[10px] text-slate-600" title="Identifiant fixe, non modifiable">{o.slug}</span>
              </div>
              <label className={etiquette}>Nom
                <input value={brouillon.name} onChange={e => setBrouillon({ ...brouillon, name: e.target.value })} className="osiris-input text-xs w-full" />
              </label>
              <label className={etiquette}>Collecteur Zabbix — vide = pas de supervision
                <input value={brouillon.zabbix_server} placeholder="ex : 192.0.2.130" onChange={e => setBrouillon({ ...brouillon, zabbix_server: e.target.value })} className="osiris-input text-xs font-mono w-full" />
              </label>
              <label className={etiquette}>Webhook de notification (Teams, Slack, Discord…) — vide = aucune
                <input value={brouillon.webhook_url} placeholder="https://…" onChange={e => setBrouillon({ ...brouillon, webhook_url: e.target.value })} className="osiris-input text-xs font-mono w-full" />
              </label>
              <div className="grid grid-cols-2 gap-2">
                <label className={etiquette}>Préfixe MAC imposé — vide = MAC inchangée
                  <input value={brouillon.mac_prefix} placeholder="ex : 02aabbcc" onChange={e => setBrouillon({ ...brouillon, mac_prefix: e.target.value })} className="osiris-input text-xs font-mono w-full" />
                </label>
                {/* Écriture seule : l'API ne renvoie jamais le mot de passe */}
                <label className={etiquette}>Mot de passe BIOS — {o.has_bios_password ? 'défini, saisir pour remplacer' : 'non défini'}
                  <input type="password" autoComplete="new-password" value={brouillon.bios_password} onChange={e => setBrouillon({ ...brouillon, bios_password: e.target.value })} className="osiris-input text-xs font-mono w-full" />
                </label>
              </div>
              <div className="flex items-center gap-2 pt-1">
                <button type="button" onClick={() => supprimer(o)} className="text-[10px] text-red-400 hover:text-red-300 mr-auto">Supprimer l'organisation…</button>
                <button type="button" onClick={fermer} className="osiris-btn-ghost text-xs px-3 border border-slate-700 rounded">Annuler</button>
                <button type="button" onClick={() => enregistrer(o)} disabled={envoi || !brouillon.name.trim()} className="osiris-btn text-xs px-4 disabled:opacity-50">Enregistrer</button>
              </div>
            </li>
          ) : (
            <li key={o.id} className="flex items-start justify-between gap-3 border-b border-slate-800/50 pb-2">
              <div className="min-w-0 space-y-0.5">
                <p className="text-sm text-white font-medium">{o.name} <span className="font-mono text-[10px] text-slate-600">{o.slug}</span></p>
                {/* Ce que l'organisation fait, lisible sans ouvrir la fiche */}
                <p className="text-[10px] leading-relaxed">
                  {o.zabbix_server
                    ? <span className="text-slate-400">Supervisée via <span className="font-mono">{o.zabbix_server}</span></span>
                    : <span className="text-amber-400">Pas de supervision</span>}
                  <span className="text-slate-700"> · </span>
                  <span className="text-slate-400">{o.webhook_url ? 'Notifications actives' : 'Pas de notification'}</span>
                  {o.mac_prefix && <><span className="text-slate-700"> · </span><span className="text-slate-400">MAC imposée <span className="font-mono">{o.mac_prefix}</span></span></>}
                  <span className="text-slate-700"> · </span>
                  <span className="text-slate-400">BIOS {o.has_bios_password ? 'protégé' : 'sans mot de passe'}</span>
                </p>
              </div>
              <button type="button" onClick={() => ouvrir(o)} disabled={enEdition !== null}
                className="osiris-action-btn flex-shrink-0 disabled:opacity-30" title={`Modifier ${o.name}`}>
                <IcoPencil />
              </button>
            </li>
          ))}
          {orgs.length === 0 && <li className="text-slate-600 text-xs">Aucune organisation pour l'instant : créez la première à droite.</li>}
        </ul>
      </div>

      {/* ── Ce que j'ajoute ─────────────────────────────────────────────── */}
      <form onSubmit={creer} className="border border-dashed border-slate-700 rounded p-5 space-y-3">
        <h2 className={titre}>+ Nouvelle organisation</h2>
        <label className={etiquette}>Nom du client
          <input required value={nouveauNom} placeholder="ex : Acme"
            onChange={e => { setNouveauNom(e.target.value); if (!slugTouche) setNouveauSlug(slugDepuisNom(e.target.value)) }}
            className="osiris-input text-xs w-full" />
        </label>
        <label className={etiquette}>Identifiant court — proposé d'après le nom, non modifiable ensuite
          <input required value={nouveauSlug} pattern="[a-z0-9]+(-[a-z0-9]+)*" title="Minuscules, chiffres et tirets"
            onChange={e => { setNouveauSlug(e.target.value); setSlugTouche(true) }}
            className="osiris-input text-xs font-mono w-full" />
        </label>
        <p className="text-[10px] text-slate-600">Supervision, notifications et BIOS se règlent ensuite, sur sa fiche.</p>
        <button type="submit" disabled={envoi || !nouveauNom.trim() || !nouveauSlug} className="osiris-btn text-xs w-full disabled:opacity-50">Créer l'organisation</button>
      </form>
    </div>
  )
}

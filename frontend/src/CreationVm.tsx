// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { useRef, useState } from 'react'
import { toast } from 'sonner'
import type { GabaritOsiris, Hypervisor, NetworkDefaults, Organization, Profile, ProxmoxNetwork, ProxmoxNode, ProxmoxTemplate } from './types'
import { authHeader } from './types'
import { buildCreateVmPayload, champsManquants, completerPrefixeCidr, dansLeReseau, imageDuProfilIgnoree,
         adressageFixeImpossible, avecProfil, gabaritsPourMode, gabaritParDefaut, modeParDefaut, profilsPourVm,
         FORMULAIRE_VIDE, LIBELLE_MODE, recapVm, etapesVm, reseauxPourVm, stockageParDefaut,
         adressesPrises, occupantDe, plagesAdresses, type UsageReseau } from './vmForm'
import { ResumeProfil } from './ResumeProfil'
import { ChampEnCours, Spinner } from './Skeleton'
import { IcoX } from './icons'
import { MAX_DISQUES, erreursDisques, libelleDepuisMontage, nouveauDisque, type DisqueForm } from './disquesForm'

const API_URL = import.meta.env.VITE_API_URL ?? ''

const ETAT_AGENT: Record<GabaritOsiris['etat'], string> = {
  a_jour: '',
  perime: ' — agent ancien',
  inconnu: ' — agent de version inconnue',
}

interface CreationVmProps {
  token: string
  hypervisors: Hypervisor[]
  profiles: Profile[]
  organizations: Organization[]
  selectedOrg: number | null
  onVmCreated: () => void
  onClose: () => void
}

/** Création d'une VM, rangée par décision plutôt que dans l'ordre des tables.
 *
 *  L'ancien formulaire alignait une vingtaine de champs et quatorze paragraphes
 *  d'explication, tous au même niveau : l'OU AD pesait autant à l'œil que le nom
 *  de la machine, et il fallait tout lire pour savoir ce qui comptait. Ici, trois
 *  blocs répondent à « quelle machine », « où » et « à quelle adresse » ; ce qu'on
 *  ne touche presque jamais — mode d'amorçage, gabarit matériel déjà repris du
 *  profil, OU, dossier, script — est replié sous « Options avancées », avec son
 *  résumé visible. Rien n'a disparu : c'est rangé. */
export function CreationVm({ token, hypervisors, profiles, organizations, selectedOrg, onVmCreated, onClose }: CreationVmProps) {
  const [avance, setAvance]             = useState(false)
  const [vmHvId, setVmHvId]             = useState<number | ''>('')
  const [vmNode, setVmNode]             = useState('')
  const [vmNodes, setVmNodes]           = useState<ProxmoxNode[]>([])
  const [vmStorages, setVmStorages]     = useState<{storage:string;type:string;avail_gb:number;total_gb:number;shared?:boolean}[]>([])
  const [vmNetworks, setVmNetworks]     = useState<ProxmoxNetwork[]>([])
  const [tousReseaux, setTousReseaux]   = useState(false)
  // Dossiers vSphere. Liste vide sur Proxmox, qui n'en a pas : le champ
  // disparaît alors du formulaire au lieu d'y proposer un choix inexistant.
  const [vmFolders, setVmFolders]       = useState<{ path: string }[]>([])
  const [vmNetDef, setVmNetDef]         = useState<NetworkDefaults | null>(null)
  // Adresses déjà utilisées sur le réseau choisi, lues sur TOUTES les VM de
  // l'hyperviseur — plus seulement les fiches d'OSIRIS
  const [usage, setUsage]               = useState<UsageReseau | null>(null)
  const [usageEnCours, setUsageEnCours] = useState(false)
  const [vmTemplates, setVmTemplates]   = useState<ProxmoxTemplate[]>([])
  // Une liste vide pendant qu'elle charge s'affichait « Aucun modèle sur cet
  // hyperviseur » : douze secondes sur un vCenter, de quoi croire ses gabarits
  // disparus (vu le 18/09). « Je cherche » et « il n'y en a pas » se distinguent.
  const [gabaritsEnCours, setGabaritsEnCours] = useState(false)
  const [noeudsEnCours, setNoeudsEnCours]       = useState(false)
  const [stockagesEnCours, setStockagesEnCours] = useState(false)
  const [reseauxEnCours, setReseauxEnCours]     = useState(false)
  // Présélection : quelqu'un qui découvre l'outil doit trouver un bon choix déjà fait
  const [vmForm, setVmForm]             = useState(() => avecProfil(
    { ...FORMULAIRE_VIDE, organization_id: selectedOrg ?? '' as number | '' },
    profilsPourVm(profiles, FORMULAIRE_VIDE.os).utilisables[0]))
  const [vmCreating, setVmCreating]     = useState(false)
  // Le formulaire rempli passe d'abord par un récapitulatif : créer une VM
  // réserve des ressources et démarre une machine, ça se relit avant.
  const [recap, setRecap]               = useState(false)

  // Hyperviseur et nœud réellement choisis À L'INSTANT. Chaque réponse s'y
  // compare avant d'écrire : changer d'hyperviseur pendant qu'une liste charge
  // laissait la réponse la plus LENTE gagner — des gabarits Proxmox affichés
  // sous le vCenter, constaté le 18/09. Un état React ne suffit pas : la
  // closure du fetch en garde la valeur d'origine.
  const choixCourant = useRef<{ hv: number | ''; noeud: string }>({ hv: '', noeud: '' })
  const toujours = (hvId: number, noeud?: string) =>
    choixCourant.current.hv === hvId && (noeud === undefined || choixCourant.current.noeud === noeud)

  const typeDe = (hvId: number | '') => hypervisors.find(h => h.id === Number(hvId))?.type

  const chargerRessources = (hvId: number, node: string) => {
    choixCourant.current = { hv: hvId, noeud: node }
    setVmStorages([]); setVmNetworks([]); setVmNetDef(null); setUsage(null)
    const h = authHeader(token)
    setStockagesEnCours(true); setReseauxEnCours(true)
    fetch(`${API_URL}/hypervisors/${hvId}/nodes/${node}/storages`, { headers: h })
      .then(r => r.json())
      .then((s: typeof vmStorages) => {
        if (!toujours(hvId, node)) return
        setVmStorages(s)
        // Le partagé le plus spacieux, ou le seul stockage : un bon choix déjà fait
        const defaut = stockageParDefaut(s)
        if (defaut) setVmForm(f => ({ ...f, storage: f.storage || defaut }))
      }).catch(() => {})
      .finally(() => { if (toujours(hvId, node)) setStockagesEnCours(false) })
    fetch(`${API_URL}/hypervisors/${hvId}/nodes/${node}/networks`, { headers: h })
      .then(r => r.json()).then(n => { if (toujours(hvId, node)) setVmNetworks(n) }).catch(() => {})
      .finally(() => { if (toujours(hvId, node)) setReseauxEnCours(false) })
  }

  const choisirHyperviseur = (hvId: number) => {
    choixCourant.current = { hv: hvId, noeud: '' }
    setVmHvId(hvId); setVmNode(''); setVmStorages([]); setVmNetworks([]); setVmNodes([]); setVmNetDef(null); setUsage(null)
    setVmFolders([])
    setVmForm(f => ({ ...f, storage: '', bridge: '', folder: '', template_id: '', iso: '',
                      boot_mode: modeParDefaut(typeDe(hvId), f.os) }))
    fetch(`${API_URL}/hypervisors/${hvId}/folders`, { headers: authHeader(token) })
      .then(r => r.json()).then(d => { if (toujours(hvId)) setVmFolders(d) }).catch(() => {})
    // Les templates sont ceux de TOUT l'hyperviseur, indépendamment du nœud : sur un
    // stockage partagé, le disque d'un template est lisible par tous les nœuds, et
    // OSIRIS sait cloner vers celui qu'on choisit. Les lier au nœud enfermait le
    // formulaire — un template posé sur un nœud condamnait ses VM à ce nœud.
    setVmTemplates([])
    setGabaritsEnCours(true)
    fetch(`${API_URL}/hypervisors/${hvId}/templates`, { headers: authHeader(token) })
      .then(r => r.ok ? r.json() : [])
      .then(t => {
        if (!toujours(hvId)) return
        const modeles: ProxmoxTemplate[] = Array.isArray(t) ? t : []
        setVmTemplates(modeles)
        // Le gabarit de la distribution choisie, déjà sélectionné
        setVmForm(f => ({ ...f, template_id: f.template_id || gabaritParDefaut(modeles, f.boot_mode, f.os) }))
      })
      .catch(() => {})
      .finally(() => { if (toujours(hvId)) setGabaritsEnCours(false) })
    setNoeudsEnCours(true)
    fetch(`${API_URL}/hypervisors/${hvId}/nodes`, { headers: authHeader(token) })
      .then(r => r.json()).then((nodes: ProxmoxNode[]) => {
        if (!toujours(hvId)) return
        setVmNodes(nodes)
        if (nodes.length === 1) {
          setVmNode(nodes[0].node)
          chargerRessources(hvId, nodes[0].node)
        }
      }).catch(() => {})
      .finally(() => { if (toujours(hvId)) setNoeudsEnCours(false) })
  }

  const choisirNoeud = (node: string) => {
    setVmNode(node)
    setVmStorages([]); setVmNetworks([]); setVmNetDef(null); setUsage(null)
    setVmForm(f => ({ ...f, storage: '', bridge: '' }))
    if (vmHvId) chargerRessources(Number(vmHvId), node)
  }

  // Choisir un réseau, c'est aussi choisir une passerelle et un DNS : ces deux
  // valeurs appartiennent au réseau, pas à la machine. On ne remplit que les champs
  // encore vides — une saisie de l'opérateur n'est jamais écrasée par une
  // proposition, même mieux informée.
  const choixReseau = useRef('')
  const choisirReseau = (bridge: string) => {
    choixReseau.current = bridge
    setVmForm(f => ({ ...f, bridge }))
    setVmNetDef(null); setUsage(null)
    if (!vmHvId || !vmNode || !bridge) return
    fetch(`${API_URL}/hypervisors/${vmHvId}/nodes/${vmNode}/network-defaults?bridge=${encodeURIComponent(bridge)}`,
          { headers: authHeader(token) })
      .then(r => r.ok ? r.json() : null)
      .then((d: NetworkDefaults | null) => {
        // Même garde : un autre réseau a pu être choisi entre-temps
        if (!d || !toujours(Number(vmHvId), vmNode) || choixReseau.current !== bridge) return
        setVmNetDef(d)
        setVmForm(f => ({
          ...f,
          gateway:     f.gateway     || d.gateway,
          dns_servers: f.dns_servers || d.dns_servers,
        }))
      })
      .catch(() => {})
    // À part : lire chaque VM prend quelques secondes, la passerelle n'attend pas
    const hvId = Number(vmHvId)
    setUsageEnCours(true)
    fetch(`${API_URL}/hypervisors/${hvId}/network-usage?bridge=${encodeURIComponent(bridge)}`,
          { headers: authHeader(token) })
      .then(r => r.ok ? r.json() : null)
      .then((u: UsageReseau | null) => {
        if (toujours(hvId) && choixReseau.current === bridge) setUsage(u)
      })
      .catch(() => {})
      .finally(() => { if (toujours(hvId) && choixReseau.current === bridge) setUsageEnCours(false) })
  }

  // L'adresse est saisie par l'opérateur — OSIRIS n'en propose jamais. Mais quand le
  // préfixe du réseau est connu, l'oubli du « /24 » n'a pas à coûter un aller-retour
  // avec le serveur : on complète ce qui manque, sans toucher au reste.
  const completerPrefixe = () => {
    if (!vmNetDef?.prefixe) return
    setVmForm(f => ({ ...f, ip_cidr: completerPrefixeCidr(f.ip_cidr, vmNetDef.prefixe) }))
  }

  const creer = (e: React.FormEvent) => {
    e.preventDefault()
    if (!vmHvId || !vmNode) return
    if (!recap) { setRecap(true); return }
    setVmCreating(true)
    fetch(`${API_URL}/hypervisors/${vmHvId}/create-vm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(token) },
      body: JSON.stringify(charge),
    }).then(async r => {
      if (!r.ok) { const e = await r.json(); throw new Error(e.detail ?? 'Erreur') }
      return r.json()
    }).then(data => {
      // Seul le PXE attend quelque chose : un clone démarre seul et rappelle OSIRIS.
      // Annoncer « en attente de boot PXE » après un clone laissait croire qu'il
      // restait une action à faire.
      toast.success(
        vmForm.boot_mode === 'pxe'
          ? `VM "${data.hostname}" créée (VMID ${data.vm_id}) - en attente de boot PXE`
          : `VM "${data.hostname}" créée (VMID ${data.vm_id}) - démarrage en cours`
      )
      onVmCreated()
      onClose()
    }).catch(err => toast.error(err.message))
      .finally(() => setVmCreating(false))
  }

  // Recalculés à chaque frappe : ils ne bloquent rien, ils avertissent. Un VLAN peut
  // légitimement porter plusieurs réseaux, et OSIRIS ne voit que ses propres fiches —
  // dans les deux cas c'est l'opérateur qui tranche, pas nous.
  const typeHv        = typeDe(vmHvId)
  const sansAdressage = adressageFixeImpossible(typeHv, vmForm.boot_mode)
  const adresseSaisie = vmForm.ip_cidr.split('/')[0].trim()
  const horsReseau    = !!(vmNetDef?.reseau && vmForm.ip_cidr
                           && dansLeReseau(vmForm.ip_cidr, vmNetDef.reseau) === false)
  const prises        = adressesPrises(usage, vmNetDef?.occupees ?? [])
  const occupant      = occupantDe(adresseSaisie, prises)
  const provenance    = vmNetDef
    ? [...new Set(Object.values(vmNetDef.origines))]
        .map(o => o === 'bridge' ? "lu sur l'hyperviseur" : 'repris des déploiements précédents')
        .join(' · ')
    : ''

  const profilsVm = profilsPourVm(profiles, vmForm.os)
  const profilEffectif = profiles.find(p => String(p.id) === String(vmForm.profile_id))
  // Sans profil, le serveur retomberait sur le plus ancien de l'OS ; sans accès,
  // il refuserait. Dans les deux cas, autant le dire ici, bouton grisé.
  const vmSansProfil = !profilEffectif
  const vmInaccessible = vmSansProfil || Boolean(profilEffectif?.resume?.alerte)
  const manquants = champsManquants(vmForm, Boolean(vmHvId), vmNode)
  // Linux seulement : sous Windows, la liste n'est pas envoyée
  const disquesInvalides = vmForm.os !== 'windows' && erreursDisques(vmForm.disques).length > 0
  const clone = vmForm.boot_mode !== 'pxe'
  // Stockage et réseau dépendent du nœud : tant qu'il n'est pas connu, ils attendent aussi
  const attenteStockage = stockagesEnCours || (noeudsEnCours && !vmNode)
  const attenteReseau   = reseauxEnCours || (noeudsEnCours && !vmNode)
  const gabarits = gabaritsPourMode(vmTemplates, vmForm.boot_mode, vmForm.os)
  const reseaux  = reseauxPourVm(vmNetworks, tousReseaux, vmForm.bridge)
  const gabaritChoisi = vmTemplates.find(t => String(t.vmid) === String(vmForm.template_id))

  const resumeAvance = [
    LIBELLE_MODE[vmForm.boot_mode],
    vmFolders.length > 0 && (vmForm.folder || 'dossier racine'),
    vmForm.ou && `OU ${vmForm.ou}`,
    vmForm.post_script.trim() && 'script post-install',
  ].filter(Boolean).join(' · ')

  // Ce qui part au serveur, et ce que montre le récapitulatif : UN seul objet.
  // Un clone nu Proxmox n'affiche pas l'adresse (champ grisé) mais la gardait
  // en mémoire et l'envoyait — refusée en 400 après coup. Elle part vide.
  const charge = buildCreateVmPayload(
    sansAdressage ? { ...vmForm, ip_cidr: '', gateway: '', dns_servers: '' } : vmForm, vmNode)
  const reseauChoisi = vmNetworks.find(n => n.iface === vmForm.bridge)
  const stockageChoisi = vmStorages.find(s => s.storage === vmForm.storage)
  // Les avertissements du formulaire, repris tels quels au récapitulatif : lus
  // une première fois ou non, ils se relisent au moment de valider.
  const aVerifier = [
    horsReseau && `${adresseSaisie} est hors de ${vmNetDef?.reseau} : la VM démarrerait sans pouvoir joindre personne.`,
    occupant && `${adresseSaisie} est déjà utilisée par ${occupant}.`,
    clone && gabaritChoisi?.osiris && gabaritChoisi.osiris.etat !== 'a_jour'
      && "Gabarit scellé avec un agent ancien ou de version inconnue : à resceller.",
    imageDuProfilIgnoree(vmForm.boot_mode, profilEffectif)
      && `L'image « ${profilEffectif?.win_image} » du profil ne sera pas utilisée : le système est celui du gabarit.`,
    reseauChoisi?.reserve && (reseauChoisi.reserve === 'pxe'
      ? `« ${reseauChoisi.iface} » est un réseau d'amorçage PXE : la VM pourrait y recevoir un autre installeur que celui d'OSIRIS.`
      : `« ${reseauChoisi.iface} » est un réseau de l'hyperviseur (stockage, sauvegarde, gestion) : une VM y est rarement à sa place.`),
  ].filter((a): a is string => Boolean(a))

  const titre = 'text-[10px] font-semibold uppercase tracking-widest text-slate-500'
  const aide  = 'text-[10px] text-slate-600'

  if (recap) return (
    <form onSubmit={creer} className="p-6 space-y-4">
      <p className="text-xs text-slate-400">Récapitulatif — rien n'est encore créé.</p>
      {recapVm(charge, {
        hyperviseur: hypervisors.find(h => h.id === Number(vmHvId))?.name ?? String(vmHvId),
        organisation: organizations.find(o => o.id === charge.organization_id)?.name,
        profil: profilEffectif,
        gabarit: gabaritChoisi?.name,
        reseau: reseauChoisi ? `${reseauChoisi.iface}${reseauChoisi.comments ? ` — ${reseauChoisi.comments}` : ''}` : undefined,
        stockage: stockageChoisi ? `${stockageChoisi.storage} (${stockageChoisi.avail_gb} Go libres)` : undefined,
        dossiers: vmFolders.length > 0,
      }).map(s => (
        <section key={s.titre} className="space-y-0.5">
          <p className={titre}>{s.titre}</p>
          {s.lignes.map((l, i) => (
            <p key={`${i}-${l.champs.join()}`} className={`text-xs ${l.attention ? 'text-amber-400' : 'text-slate-300'}`}>
              {l.attention && '⚠ '}{l.texte}
            </p>
          ))}
        </section>
      ))}
      <section className="space-y-0.5">
        <p className={titre}>Ce qui va se passer</p>
        <ol className="list-decimal list-inside text-xs text-slate-300 space-y-0.5">
          {etapesVm(charge, gabaritChoisi?.name).map(e => <li key={e}>{e}</li>)}
        </ol>
      </section>
      {aVerifier.length > 0 && (
        <section className="space-y-0.5 border-l-2 border-amber-500/60 pl-2">
          <p className={titre}>À vérifier</p>
          {aVerifier.map(a => <p key={a} className="text-xs text-amber-400">⚠ {a}</p>)}
        </section>
      )}
      <div className="flex gap-2">
        <button type="button" onClick={() => setRecap(false)} disabled={vmCreating}
          className="osiris-btn-ghost text-xs px-4 border border-slate-700 rounded">← Modifier</button>
        <button type="submit" autoFocus disabled={vmCreating} className="osiris-btn text-xs px-4 flex-1 disabled:opacity-50">
          {vmCreating ? 'Création en cours...' : 'Créer et démarrer la VM'}
        </button>
      </div>
    </form>
  )

  return (
    <form onSubmit={creer} className="p-6 space-y-5">

      {/* ── 1. La machine ─────────────────────────────────────────────────── */}
      <section className="space-y-2">
        <p className={titre}>1 · La machine</p>
        <div className="grid grid-cols-2 gap-2">
          <input required placeholder="Nom de la machine (ex : srv-web-01)" value={vmForm.hostname} onChange={e => setVmForm(f => ({...f, hostname: e.target.value}))} className="osiris-input text-xs font-mono" />
          <input required placeholder="Client (libellé libre)" value={vmForm.client} onChange={e => setVmForm(f => ({...f, client: e.target.value}))} className="osiris-input text-xs" />
          {/* L'organisation portait la supervision, le webhook et les reglages
              materiel, mais n'apparaissait nulle part ici : le formulaire reprenait
              en silence le filtre « Client » du haut de page. Une VM creee filtre sur
              « Tous les clients » naissait sans organisation, donc sans agent Zabbix,
              sans que rien ne le signale. Vecu le 2026-08-05. */}
          <select value={vmForm.organization_id} onChange={e => setVmForm(f => ({...f, organization_id: e.target.value === '' ? '' : Number(e.target.value)}))} className="osiris-input text-xs col-span-2">
            <option value="">Aucune organisation — la VM ne sera pas supervisée</option>
            {organizations.map(o => <option key={o.id} value={o.id}>Organisation : {o.name}</option>)}
          </select>
          <select value={vmForm.os} onChange={e => setVmForm(f => avecProfil({
              ...f, os: e.target.value, boot_mode: modeParDefaut(typeHv, e.target.value), iso: '',
              template_id: gabaritParDefaut(vmTemplates, modeParDefaut(typeHv, e.target.value), e.target.value),
            }, profilsPourVm(profiles, e.target.value).utilisables[0]))} className="osiris-input text-xs">
            <option value="ubuntu">Ubuntu</option>
            <option value="debian">Debian</option>
            <option value="windows">Windows</option>
          </select>
          {/* Pas d'option « par défaut » : elle désignait en silence le plus
              ancien profil de l'OS — pour Ubuntu, un poste sans aucune clé. Les
              profils utilisables d'abord (le premier est présélectionné à
              l'ouverture), ceux qui ne donnent aucun accès grisés en dessous,
              avec la raison : on voit pourquoi ils ne sont pas proposés. */}
          <select required value={vmForm.profile_id} onChange={e => setVmForm(f => avecProfil(f, profiles.find(p => String(p.id) === e.target.value)))} className="osiris-input text-xs">
            {!vmForm.profile_id && (
              <option value="" disabled>{profilsVm.utilisables.length ? '— Choisir un profil —' : 'Aucun profil utilisable pour cet OS'}</option>
            )}
            {profilsVm.utilisables.map(p => (
              <option key={p.id} value={p.id}>{p.name}{p.machine_type === 'server' ? ' [serveur]' : ''}</option>
            ))}
            {profilsVm.inutilisables.length > 0 && (
              <optgroup label="Inutilisables pour une VM : aucun accès">
                {profilsVm.inutilisables.map(p => (
                  <option key={p.id} value={p.id} disabled>{p.name}</option>
                ))}
              </optgroup>
            )}
          </select>
          <div className="col-span-2">
            <ResumeProfil resume={profilEffectif?.resume} />
          </div>
        </div>
      </section>

      {/* ── 2. Où la créer ────────────────────────────────────────────────── */}
      <section className="space-y-2">
        <p className={titre}>2 · Où la créer</p>
        <div className="grid grid-cols-2 gap-2">
          <ChampEnCours enCours={noeudsEnCours} cls={vmNodes.length > 1 ? '' : 'col-span-2'}>
            <select required value={vmHvId} onChange={e => choisirHyperviseur(Number(e.target.value))} className="osiris-input text-xs">
              <option value="">Hyperviseur...</option>
              {hypervisors.map(h => <option key={h.id} value={h.id}>{h.name}</option>)}
            </select>
          </ChampEnCours>
          {/* Un seul nœud (un cluster vSphere, un Proxmox isolé) : choisi d'office,
              le champ n'apparaît pas. Il ne s'affiche que s'il y a un choix à faire. */}
          {vmNodes.length > 1 && (
            <select required value={vmNode} onChange={e => choisirNoeud(e.target.value)} className="osiris-input text-xs">
              <option value="">Nœud...</option>
              {vmNodes.map(n => (
                <option key={n.node} value={n.node}>{n.node} — {n.cpu}% CPU · {n.mem_gb}/{n.maxmem_gb} Go RAM</option>
              ))}
            </select>
          )}

          {clone ? (
            <ChampEnCours enCours={gabaritsEnCours} cls="col-span-2">
            <select required value={vmForm.template_id} onChange={e => setVmForm(f => ({...f, template_id: e.target.value}))} className="osiris-input text-xs" disabled={vmTemplates.length === 0}>
              <option value="">{!vmHvId ? "Gabarit — choisir d'abord l'hyperviseur"
                : gabaritsEnCours ? "Lecture des gabarits sur l'hyperviseur…"
                : vmTemplates.length === 0 ? 'Aucun modèle sur cet hyperviseur'
                : gabarits.proposes.length === 0 && !gabarits.autresChoisissables ? 'Aucun gabarit OSIRIS pour ce système — voir Infrastructure'
                : 'Gabarit à cloner...'}</option>
              {/* Le nœud du template est affiché : il n'a plus besoin d'être celui du
                  déploiement, mais savoir où vit un modèle reste utile — c'est le
                  seul indice si un clone échoue faute de stockage partagé. */}
              {gabarits.proposes.map(t => (
                <option key={t.vmid} value={t.vmid}>{t.name}{t.osiris ? ETAT_AGENT[t.osiris.etat] : ''}{t.node ? ` · sur ${t.node}` : ''}</option>
              ))}
              {gabarits.autres.length > 0 && (
                <optgroup label={gabarits.autresChoisissables
                  ? 'Autres modèles de l\'hyperviseur'
                  : 'Sans agent OSIRIS ou autre système : un clone nu ne rappellerait jamais'}>
                  {gabarits.autres.map(t => (
                    <option key={t.vmid} value={t.vmid} disabled={!gabarits.autresChoisissables}>{t.name}{t.node ? ` · sur ${t.node}` : ''}</option>
                  ))}
                </optgroup>
              )}
            </select>
            </ChampEnCours>
          ) : (
            <p className={`${aide} col-span-2`}>Installation par le réseau (PXE) : aucun gabarit à choisir.</p>
          )}

          <ChampEnCours enCours={attenteStockage}>
          <select required value={vmForm.storage} onChange={e => setVmForm(f => ({...f, storage: e.target.value}))} className="osiris-input text-xs" disabled={vmStorages.length === 0}>
            <option value="">{attenteStockage ? 'Lecture des stockages…' : vmNode ? 'Stockage...' : 'Stockage'}</option>
            {vmStorages.map(s => <option key={s.storage} value={s.storage}>{s.storage} ({s.type}) — {s.avail_gb} Go libres</option>)}
          </select>
          </ChampEnCours>
          <ChampEnCours enCours={attenteReseau}>
          <select required value={vmForm.bridge} onChange={e => choisirReseau(e.target.value)} className="osiris-input text-xs" disabled={vmNetworks.length === 0}>
            <option value="">{attenteReseau ? 'Lecture des réseaux…' : vmNode ? 'Réseau...' : 'Réseau'}</option>
            {/* Le commentaire porté par le bridge est le nom du VLAN côté réseau
                (« ADMIN », « Clients_MUTU »…) : c'est cela que l'exploitant a en
                tête, pas « vmbr320 ». */}
            {reseaux.proposes.map(n => (
              <option key={n.iface} value={n.iface}>
                {n.iface}{n.comments ? ` — ${n.comments}` : ''}{n.cidr ? ` (${n.cidr})` : ''}
              </option>
            ))}
            {reseaux.reserves.length > 0 && (
              <optgroup label="Réseaux de l'hyperviseur et d'amorçage — rarement pour une VM">
                {reseaux.reserves.map(n => (
                  <option key={n.iface} value={n.iface}>
                    {n.iface}{n.comments ? ` — ${n.comments}` : ''} · {n.reserve === 'pxe' ? 'amorçage PXE' : "réseau de l'hyperviseur"}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
          </ChampEnCours>
        </div>
        {/* Ceph, sauvegarde, gestion, PXE d'une autre équipe : une VM qui y naît
            démarre et reste muette. Ils ne sont pas retirés, seulement rangés. */}
        {(reseaux.masques > 0 || tousReseaux) && (
          <label className="flex items-center gap-1.5 text-[10px] text-slate-500 cursor-pointer w-fit">
            <input type="checkbox" checked={tousReseaux} onChange={e => setTousReseaux(e.target.checked)} />
            Afficher aussi les réseaux de l'hyperviseur et d'amorçage{reseaux.masques > 0 ? ` (${reseaux.masques})` : ''}
          </label>
        )}

        {/* En mode gabarit, l'OS ne vient PAS du profil : il vient de l'image
            clonee. Le profil continue de decider tout le reste (jonction,
            applications, supervision), mais son image systeme est ignoree.
            Sans ce rappel, un profil nomme d'apres un OS laisse croire qu'on
            deploie cet OS-la — vecu le 2026-08-25, ou un gabarit 2022 a ete
            clone avec un profil nomme « Windows Server 2025 ». Rien n'echoue :
            on obtient juste un autre OS que celui qu'on croyait demander. */}
        {/* Un agent périmé se clone et démarre : il lui manque seulement les
            correctifs publiés depuis son scellement. On le dit, sans bloquer. */}
        {clone && gabaritChoisi?.osiris && gabaritChoisi.osiris.etat !== 'a_jour' && (
          <p className="text-[10px] text-amber-400">
            ⚠ {gabaritChoisi.osiris.etat === 'perime'
              ? "Ce gabarit a été scellé avec une version antérieure de l'agent : il lui manque les derniers correctifs. Le resceller dès que possible."
              : "Version de l'agent inconnue (gabarit marqué à la main) : le resceller permettra de savoir s'il est à jour."}
          </p>
        )}
        {clone && (
          <p className={imageDuProfilIgnoree(vmForm.boot_mode, profilEffectif) ? 'text-[10px] text-amber-400' : aide}>
            {imageDuProfilIgnoree(vmForm.boot_mode, profilEffectif) && '⚠ '}
            Le système installé est celui du gabarit, pas celui du profil.
            {imageDuProfilIgnoree(vmForm.boot_mode, profilEffectif)
              && ` L'image « ${profilEffectif?.win_image} » déclarée par ce profil ne sera pas utilisée.`}
          </p>
        )}
      </section>

      {/* ── 3. Adresse réseau ─────────────────────────────────────────────── */}
      <section className="space-y-2">
        <p className={titre}>3 · Adresse réseau <span className="normal-case font-normal text-slate-600">— vide = DHCP</span></p>
        <div className="grid grid-cols-3 gap-2">
          <input placeholder={sansAdressage ? 'indisponible dans ce mode'
                   : vmNetDef?.reseau ? `adresse dans ${vmNetDef.reseau}` : 'Adresse IP (ex : 10.0.0.60/24)'}
            value={sansAdressage ? '' : vmForm.ip_cidr} disabled={sansAdressage}
            onChange={e => setVmForm(f => ({...f, ip_cidr: e.target.value}))}
            onBlur={completerPrefixe}
            className="osiris-input text-xs font-mono disabled:opacity-40" />
          <input placeholder="Passerelle" value={sansAdressage ? '' : vmForm.gateway}
            disabled={sansAdressage}
            onChange={e => setVmForm(f => ({...f, gateway: e.target.value}))}
            className="osiris-input text-xs font-mono disabled:opacity-40" />
          {/* Exigé dès qu'une adresse fixe est saisie : sans DHCP pour en
              fournir un, la VM n'aurait AUCUN résolveur — et le dirait si peu
              qu'elle se déclarerait déployée. L'API refuse aussi, mais autant
              le dire avant d'envoyer le formulaire. */}
          <input placeholder={vmForm.ip_cidr ? 'DNS — obligatoire' : 'DNS (séparés par ,)'}
            required={!!vmForm.ip_cidr && !sansAdressage}
            value={sansAdressage ? '' : vmForm.dns_servers} disabled={sansAdressage}
            onChange={e => setVmForm(f => ({...f, dns_servers: e.target.value}))}
            className="osiris-input text-xs font-mono disabled:opacity-40" />
        </div>

        {/* Un champ qu'on ne peut pas remplir vaut mieux qu'un formulaire
            rejeté après coup — et infiniment mieux qu'une adresse acceptée
            puis perdue en silence, qui laissait la VM muette. */}
        {sansAdressage ? (
          <p className="text-[10px] text-amber-400">
            ⚠ Un clone nu sur cet hyperviseur ne peut pas recevoir d'adresse fixe. Passer en « Clone + cloud-init » (options avancées), ou laisser la VM en DHCP.
          </p>
        ) : (
          <p className={aide}>
            Obligatoire sur un réseau sans DHCP : sans adresse, la VM démarre mais ne rappelle jamais OSIRIS.
          </p>
        )}

        {/* Passerelle et DNS sont des propriétés du RÉSEAU, pas de la machine :
            les retaper de mémoire à chaque déploiement n'apporte rien qu'un
            risque de faute de frappe. L'adresse, elle, reste saisie à la main :
            même en lisant toutes les VM de l'hyperviseur, OSIRIS ne voit pas une
            machine physique ou un autre cluster, et ne peut affirmer qu'une
            adresse est libre. On dit ce qu'on sait pris, jamais ce qu'on croit
            disponible. */}
        {vmNetDef && (
          <div className="text-[10px] space-y-0.5 border-l-2 border-slate-800 pl-2">
            {vmNetDef.reseau ? (
              <p className="text-slate-500">
                Réseau <span className="font-mono text-slate-400">{vmNetDef.reseau}</span>
                {vmNetDef.gateway && <> · passerelle <span className="font-mono text-slate-400">{vmNetDef.gateway}</span></>}
                {vmNetDef.dns_servers && <> · DNS <span className="font-mono text-slate-400">{vmNetDef.dns_servers}</span></>}
                {provenance && <span className="text-slate-600"> — {provenance}</span>}
              </p>
            ) : (
              <p className="text-slate-600">
                Réseau encore inconnu d'OSIRIS : tout est à saisir, cette fois seulement — le prochain déploiement reprendra ces valeurs.
              </p>
            )}
          </div>
        )}

        {/* Ce qui est pris, jamais ce qui est libre : une machine hors de
            l'hyperviseur (physique, autre cluster) n'apparaît pas ici. */}
        {vmForm.bridge && (usageEnCours || prises.length > 0 || usage) && (
          <div className="text-[10px] space-y-0.5 border-l-2 border-slate-800 pl-2">
            {usageEnCours ? (
              <p className="text-slate-600 flex items-center gap-1.5"><Spinner cls="w-3 h-3" /> Lecture des adresses déjà utilisées sur ce réseau…</p>
            ) : (
              prises.length === 0 ? (
                <p className="text-slate-500">Aucune adresse connue sur ce réseau.</p>
              ) : plagesAdresses(prises).map(g => (
                <p key={g.prefixe} className="text-slate-500" title="Lu sur toutes les VM de l'hyperviseur (agent invité ou configuration). Une machine hors de l'hyperviseur n'y figure pas. Survoler une plage pour voir ses VM.">
                  Déjà utilisées sur <span className="font-mono text-slate-400">{g.prefixe}.x</span>
                  {' '}({g.plages.reduce((n, p) => n + p.vms.length, 0)}) :{' '}
                  {g.plages.map((p, i) => (
                    <span key={p.texte}>{i > 0 && <span className="text-slate-700"> · </span>}<span className="font-mono text-slate-300 cursor-help" title={p.vms.join('\n')}>{p.texte}</span></span>
                  ))}
                </p>
              ))
            )}
            {!usageEnCours && usage && usage.sans_adresse.length > 0 && (
              <p className="text-slate-600">
                Adresse inconnue pour {usage.sans_adresse.length} VM (éteinte, DHCP ou sans agent) : {usage.sans_adresse.join(', ')}. Elles peuvent en occuper une.
              </p>
            )}
          </div>
        )}

        {horsReseau && (
          <p className="text-[10px] text-amber-400">
            ⚠ {adresseSaisie} est hors de {vmNetDef?.reseau} : la VM démarrerait sans pouvoir joindre personne. À vérifier — un VLAN peut légitimement porter plusieurs réseaux.
          </p>
        )}
        {occupant && (
          <p className="text-[10px] text-amber-400">
            ⚠ {adresseSaisie} est déjà utilisée par {occupant}.
          </p>
        )}
      </section>

      {/* ── 4. Matériel ───────────────────────────────────────────────────── */}
      {/* Hors des options avancées : on y revient à presque chaque VM, et les
          disques en plus (nom, taille, LVM) y vivent. */}
      <section className="space-y-2">
        <p className={titre}>4 · Matériel <span className="normal-case font-normal text-slate-600">— repris du profil, modifiable</span></p>
        <div className="grid grid-cols-4 gap-2">
          <label className="flex items-center gap-1 text-[10px] text-slate-500">vCPU
            <input type="number" min={1} max={64} value={vmForm.vcpus} onChange={e => setVmForm(f => ({...f, vcpus: Number(e.target.value)}))} className="osiris-input text-xs w-full" />
          </label>
          <label className="flex items-center gap-1 text-[10px] text-slate-500">RAM Mo
            <input type="number" min={512} step={512} value={vmForm.ram_mb} onChange={e => setVmForm(f => ({...f, ram_mb: Number(e.target.value)}))} className="osiris-input text-xs w-full" />
          </label>
          <label className="flex items-center gap-1 text-[10px] text-slate-500">Système Go
            <input type="number" min={8} value={vmForm.disk_gb} onChange={e => setVmForm(f => ({...f, disk_gb: Number(e.target.value)}))} className="osiris-input text-xs w-full" />
          </label>
          {/* Windows : un seul disque de données pour l'instant */}
          {vmForm.os === 'windows' && (
            <label className="flex items-center gap-1 text-[10px] text-slate-500" title="Disque de données. 0 = aucun.">Données Go
              <input type="number" min={0} value={vmForm.data_disk_gb} onChange={e => setVmForm(f => ({...f, data_disk_gb: Number(e.target.value)}))} className="osiris-input text-xs w-full" />
            </label>
          )}
        </div>

        {/* Linux : les disques supplémentaires, chacun formaté et monté au premier
            démarrage. Le libellé se retrouve dans `lsblk` (volume LVM) et
            `lsblk -f` (étiquette) : c'est par lui qu'on reconnaît un disque. */}
        {vmForm.os !== 'windows' && (
          <div className="space-y-1.5">
            {vmForm.disques.length > 0 && (
              <div className="grid grid-cols-[4.5rem_1fr_7rem_3.5rem_4.5rem_1.5rem] gap-2 text-[10px] text-slate-600">
                <span>Taille Go</span><span>Point de montage</span><span title="Visible dans lsblk (vg_libellé-libellé) et lsblk -f">Libellé</span>
                <span title="LVM : agrandissable à chaud en ajoutant un disque">LVM</span><span>Format</span><span />
              </div>
            )}
            {vmForm.disques.map((d, i) => {
              const maj = (champ: Partial<DisqueForm>) => setVmForm(f => ({
                ...f, disques: f.disques.map((x, j) => j === i ? { ...x, ...champ } : x),
              }))
              return (
                <div key={i} className="grid grid-cols-[4.5rem_1fr_7rem_3.5rem_4.5rem_1.5rem] gap-2 items-center">
                  <input type="number" min={1} value={d.taille_gb} onChange={e => maj({ taille_gb: Number(e.target.value) })} className="osiris-input text-xs" />
                  <input value={d.point_montage} placeholder="/data"
                    onChange={e => maj({ point_montage: e.target.value, ...(d.libelleTouche ? {} : { libelle: libelleDepuisMontage(e.target.value) }) })}
                    className="osiris-input text-xs font-mono" />
                  <input value={d.libelle} maxLength={12} onChange={e => maj({ libelle: e.target.value.toLowerCase(), libelleTouche: true })}
                    className="osiris-input text-xs font-mono" />
                  <label className="flex justify-center"><input type="checkbox" checked={d.lvm} onChange={e => maj({ lvm: e.target.checked })} /></label>
                  <select value={d.systeme_fichiers} onChange={e => maj({ systeme_fichiers: e.target.value as DisqueForm['systeme_fichiers'] })} className="osiris-input text-xs">
                    <option value="ext4">ext4</option>
                    <option value="xfs">xfs</option>
                  </select>
                  <button type="button" onClick={() => setVmForm(f => ({ ...f, disques: f.disques.filter((_, j) => j !== i) }))}
                    className="osiris-action-btn osiris-action-btn--danger" title="Retirer ce disque"><IcoX /></button>
                </div>
              )
            })}
            {erreursDisques(vmForm.disques).map(e => <p key={e} className="text-[10px] text-amber-400">⚠ {e}</p>)}
            <div className="flex items-center gap-3">
              {vmForm.disques.length < MAX_DISQUES && (
                <button type="button" onClick={() => setVmForm(f => ({ ...f, disques: [...f.disques, nouveauDisque(f.disques)] }))}
                  className="osiris-btn-ghost text-[10px] border border-slate-700 rounded px-2 py-0.5">+ Ajouter un disque</button>
              )}
              <p className={aide}>
                {vmForm.disques.length === 0 ? 'Aucun disque supplémentaire.' : "LVM : agrandissable à chaud. xfs ne se réduit jamais."}
              </p>
            </div>
          </div>
        )}
      </section>

      {/* ── Options avancées ──────────────────────────────────────────────── */}
      <section className="border border-slate-800/60 rounded">
        <button type="button" onClick={() => setAvance(a => !a)}
          className="w-full flex items-center justify-between gap-3 px-3 py-2 text-left">
          <span className={titre}>{avance ? '▾' : '▸'} Options avancées</span>
          {!avance && <span className="text-[10px] text-slate-500 truncate">{resumeAvance}</span>}
        </button>
        {avance && (
          <div className="px-3 pb-3 space-y-3">
            <div className="space-y-1">
              <p className={aide}>Mode de création</p>
              <div className="flex gap-2">
                {/* cloud-init est spécifique Linux (user-data, apt) : jamais proposé à Windows */}
                {(vmForm.os === 'windows' ? ['template', 'pxe'] as const : ['template', 'cloudinit', 'pxe'] as const).map(mode => (
                  <button key={mode} type="button"
                    onClick={() => setVmForm(f => ({...f, boot_mode: mode, iso: '',
                      template_id: mode === 'pxe' ? '' : gabaritParDefaut(vmTemplates, mode, f.os)}))}
                    className={`flex-1 py-1.5 rounded text-xs border transition-colors ${vmForm.boot_mode === mode ? 'bg-blue-600/20 border-blue-500 text-blue-300' : 'bg-slate-900 border-slate-700 text-slate-500 hover:border-slate-500'}`}>
                    {LIBELLE_MODE[mode]}{mode === modeParDefaut(typeHv, vmForm.os) ? ' (recommandé)' : ''}
                  </button>
                ))}
              </div>
              <p className={aide}>
                {vmForm.boot_mode === 'pxe'
                  ? (vmForm.os === 'windows'
                      ? "WinPE livré en CD-ROM : la VM s'installe puis rappelle OSIRIS. Le plus lent."
                      : "Démarrage réseau puis installation complète : la VM s'enregistre au premier boot. Le plus lent.")
                  : vmForm.boot_mode === 'template'
                    ? "Copie du gabarit avec une carte réseau neuve ; l'agent OSIRIS gravé dans le gabarit rappelle au démarrage (~2 min)."
                    : 'Copie du gabarit, configurée au démarrage par cloud-init (nom, réseau, comptes). ~30 s.'}
              </p>
              {vmForm.boot_mode === 'pxe' && (
                <input placeholder="ISO Proxmox (ex: local:iso/ubuntu-24.04.iso) — optionnel" value={vmForm.iso} onChange={e => setVmForm(f => ({...f, iso: e.target.value}))} className="osiris-input text-xs font-mono w-full" />
              )}
            </div>

            <div className="grid grid-cols-2 gap-2">
              {/* Rangement vSphere. Absent sur Proxmox : la liste revient vide. */}
              {vmFolders.length > 0 && (
                <select value={vmForm.folder} onChange={e => setVmForm(f => ({...f, folder: e.target.value}))} className="osiris-input text-xs">
                  <option value="">Dossier : racine du datacenter</option>
                  {vmFolders.map(d => <option key={d.path} value={d.path}>{d.path}</option>)}
                </select>
              )}
              <input placeholder="OU Active Directory (optionnel)" value={vmForm.ou} onChange={e => setVmForm(f => ({...f, ou: e.target.value}))} className={`osiris-input text-xs font-mono ${vmFolders.length > 0 ? '' : 'col-span-2'}`} />
            </div>

            <div className="space-y-1">
              <textarea rows={3} value={vmForm.post_script}
                onChange={e => setVmForm(f => ({...f, post_script: e.target.value}))}
                placeholder={vmForm.os === 'windows' ? 'Script PowerShell propre à cette VM (optionnel)' : 'Script bash propre à cette VM (optionnel)'}
                className="osiris-input text-[10px] font-mono w-full resize-y" />
              {/* Joue APRES le script du profil : le profil pose le socle commun,
                  celui-ci ne vaut que pour cette VM. Une erreur est journalisee sans
                  faire echouer le deploiement. */}
              <p className={aide}>
                Exécuté en root après le script du profil. Il est gravé dans la configuration de la VM : y faire chercher un secret, jamais l'y écrire.
              </p>
            </div>
          </div>
        )}
      </section>

      <div className="space-y-1.5">
        {vmInaccessible ? (
          <p className="text-[10px] text-red-400">
            {!vmSansProfil
              ? "Création impossible avec ce profil : personne ne pourrait entrer dans la VM. Lui ajouter une clé SSH ou le mot de passe root de secours, ou en choisir un autre."
              : profilsVm.utilisables.length
                ? 'Choisir un profil de déploiement.'
                : "Aucun profil de cet OS ne donne accès à une VM. En créer un avec une clé SSH (Administration → Profils), ou ajouter une clé à un profil existant."}
          </p>
        ) : manquants.length > 0 && (
          <p className="text-[10px] text-slate-500">À compléter : {manquants.join(', ')}</p>
        )}
        <div className="flex gap-2">
          <button type="button" onClick={onClose} className="osiris-btn-ghost text-xs px-4 border border-slate-700 rounded">Annuler</button>
          <button type="submit" disabled={vmInaccessible || manquants.length > 0 || disquesInvalides} className="osiris-btn text-xs px-4 flex-1 disabled:opacity-50">
            Vérifier avant de créer →
          </button>
        </div>
      </div>
    </form>
  )
}

// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { useRef, useState } from 'react'
import { toast } from 'sonner'
import type { GabaritOsiris, Hypervisor, NetworkDefaults, Organization, Profile, ProxmoxNetwork, ProxmoxNode, ProxmoxTemplate } from './types'
import { authHeader } from './types'
import { buildCreateVmPayload, champsManquants, completerPrefixeCidr, dansLeReseau, imageDuProfilIgnoree,
         adressageFixeImpossible, avecProfil, gabaritsPourMode, modeParDefaut, profilsPourVm, type ModeVm } from './vmForm'
import { ResumeProfil } from './ResumeProfil'
import { ChampEnCours } from './Skeleton'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://10.0.0.1:8000'

const FORMULAIRE_VIDE = { organization_id: '' as number | '', hostname: '', client: '', os: 'ubuntu', profile_id: '', ou: '', storage: '', bridge: '', folder: '', vcpus: 2, ram_mb: 2048, disk_gb: 20, data_disk_gb: 0, ip_cidr: '', gateway: '', dns_servers: '', iso: '', boot_mode: 'template' as ModeVm, template_id: '', post_script: '' }

const ETAT_AGENT: Record<GabaritOsiris['etat'], string> = {
  a_jour: '',
  perime: ' — agent ancien',
  inconnu: ' — agent de version inconnue',
}

const LIBELLE_MODE: Record<ModeVm, string> = {
  template: 'Clone du gabarit',
  cloudinit: 'Clone + cloud-init',
  pxe: 'Installation PXE',
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
  const [vmStorages, setVmStorages]     = useState<{storage:string;type:string;avail_gb:number;total_gb:number}[]>([])
  const [vmNetworks, setVmNetworks]     = useState<ProxmoxNetwork[]>([])
  // Dossiers vSphere. Liste vide sur Proxmox, qui n'en a pas : le champ
  // disparaît alors du formulaire au lieu d'y proposer un choix inexistant.
  const [vmFolders, setVmFolders]       = useState<{ path: string }[]>([])
  const [vmNetDef, setVmNetDef]         = useState<NetworkDefaults | null>(null)
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
    setVmStorages([]); setVmNetworks([]); setVmNetDef(null)
    const h = authHeader(token)
    setStockagesEnCours(true); setReseauxEnCours(true)
    fetch(`${API_URL}/hypervisors/${hvId}/nodes/${node}/storages`, { headers: h })
      .then(r => r.json())
      .then((s: typeof vmStorages) => {
        if (!toujours(hvId, node)) return
        setVmStorages(s)
        // Un seul stockage : il n'y a rien à décider, le champ n'a pas à le demander
        if (s.length === 1) setVmForm(f => ({ ...f, storage: s[0].storage }))
      }).catch(() => {})
      .finally(() => { if (toujours(hvId, node)) setStockagesEnCours(false) })
    fetch(`${API_URL}/hypervisors/${hvId}/nodes/${node}/networks`, { headers: h })
      .then(r => r.json()).then(n => { if (toujours(hvId, node)) setVmNetworks(n) }).catch(() => {})
      .finally(() => { if (toujours(hvId, node)) setReseauxEnCours(false) })
  }

  const choisirHyperviseur = (hvId: number) => {
    choixCourant.current = { hv: hvId, noeud: '' }
    setVmHvId(hvId); setVmNode(''); setVmStorages([]); setVmNetworks([]); setVmNodes([]); setVmNetDef(null)
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
      .then(t => { if (toujours(hvId)) setVmTemplates(Array.isArray(t) ? t : []) })
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
    setVmStorages([]); setVmNetworks([]); setVmNetDef(null)
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
    setVmNetDef(null)
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
    setVmCreating(true)
    fetch(`${API_URL}/hypervisors/${vmHvId}/create-vm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(token) },
      body: JSON.stringify(buildCreateVmPayload(vmForm, vmNode)),
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
  const dejaPrise     = !!(adresseSaisie && vmNetDef?.occupees.includes(adresseSaisie))
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
  const clone = vmForm.boot_mode !== 'pxe'
  // Stockage et réseau dépendent du nœud : tant qu'il n'est pas connu, ils attendent aussi
  const attenteStockage = stockagesEnCours || (noeudsEnCours && !vmNode)
  const attenteReseau   = reseauxEnCours || (noeudsEnCours && !vmNode)
  const gabarits = gabaritsPourMode(vmTemplates, vmForm.boot_mode, vmForm.os)
  const gabaritChoisi = vmTemplates.find(t => String(t.vmid) === String(vmForm.template_id))

  const resumeAvance = [
    LIBELLE_MODE[vmForm.boot_mode],
    `${vmForm.vcpus} vCPU`,
    `${vmForm.ram_mb >= 1024 ? `${+(vmForm.ram_mb / 1024).toFixed(1)} Go` : `${vmForm.ram_mb} Mo`} RAM`,
    `${vmForm.disk_gb} Go${vmForm.data_disk_gb ? ` + ${vmForm.data_disk_gb} Go /data` : ''}`,
    vmFolders.length > 0 && (vmForm.folder || 'dossier racine'),
    vmForm.ou && `OU ${vmForm.ou}`,
    vmForm.post_script.trim() && 'script post-install',
  ].filter(Boolean).join(' · ')

  const titre = 'text-[10px] font-semibold uppercase tracking-widest text-slate-500'
  const aide  = 'text-[10px] text-slate-600'

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
              ...f, os: e.target.value, boot_mode: modeParDefaut(typeHv, e.target.value), template_id: '', iso: '',
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
            {vmNetworks.map(n => (
              <option key={n.iface} value={n.iface}>
                {n.iface}{n.comments ? ` — ${n.comments}` : ''}{n.cidr ? ` (${n.cidr})` : ''}
              </option>
            ))}
          </select>
          </ChampEnCours>
        </div>

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
            risque de faute de frappe. L'adresse, elle, reste saisie à la main —
            OSIRIS ne voit que ses propres fiches et ne peut affirmer qu'une
            adresse est libre. On dit donc ce qu'on sait pris, jamais ce qu'on
            croit disponible. */}
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
            {vmNetDef.occupees.length > 0 && (
              <p className="text-slate-600" title="OSIRIS ignore les machines posées à la main : cette liste dit ce qui est pris, jamais ce qui est libre.">
                Déjà prises par OSIRIS : <span className="font-mono">{vmNetDef.occupees.join(', ')}</span>
              </p>
            )}
          </div>
        )}

        {horsReseau && (
          <p className="text-[10px] text-amber-400">
            ⚠ {adresseSaisie} est hors de {vmNetDef?.reseau} : la VM démarrerait sans pouvoir joindre personne. À vérifier — un VLAN peut légitimement porter plusieurs réseaux.
          </p>
        )}
        {dejaPrise && (
          <p className="text-[10px] text-amber-400">
            ⚠ {adresseSaisie} est déjà l'adresse d'une machine enregistrée dans OSIRIS.
          </p>
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
                    onClick={() => setVmForm(f => ({...f, boot_mode: mode, template_id: '', iso: ''}))}
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

            <div className="space-y-1">
              <p className={aide}>Matériel — repris du profil, modifiable</p>
              <div className="grid grid-cols-4 gap-2">
                <label className="flex items-center gap-1 text-[10px] text-slate-500">vCPU
                  <input type="number" min={1} max={64} value={vmForm.vcpus} onChange={e => setVmForm(f => ({...f, vcpus: Number(e.target.value)}))} className="osiris-input text-xs w-full" />
                </label>
                <label className="flex items-center gap-1 text-[10px] text-slate-500">RAM Mo
                  <input type="number" min={512} step={512} value={vmForm.ram_mb} onChange={e => setVmForm(f => ({...f, ram_mb: Number(e.target.value)}))} className="osiris-input text-xs w-full" />
                </label>
                <label className="flex items-center gap-1 text-[10px] text-slate-500">Disque Go
                  <input type="number" min={8} value={vmForm.disk_gb} onChange={e => setVmForm(f => ({...f, disk_gb: Number(e.target.value)}))} className="osiris-input text-xs w-full" />
                </label>
                <label className="flex items-center gap-1 text-[10px] text-slate-500" title="Second disque, formaté et monté sur /data au premier démarrage. 0 = aucun.">/data Go
                  <input type="number" min={0} value={vmForm.data_disk_gb} onChange={e => setVmForm(f => ({...f, data_disk_gb: Number(e.target.value)}))} className="osiris-input text-xs w-full" />
                </label>
              </div>
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
          <button type="submit" disabled={vmCreating || vmInaccessible || manquants.length > 0} className="osiris-btn text-xs px-4 flex-1 disabled:opacity-50">
            {vmCreating ? 'Création en cours...' : 'Créer et démarrer la VM'}
          </button>
        </div>
      </div>
    </form>
  )
}

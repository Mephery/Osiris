// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { useState } from 'react'

export function CopyBlock({ label, code }: { label: string; code: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-[9px] uppercase tracking-widest text-slate-600">{label}</span>
        <button onClick={copy} className="text-[10px] text-slate-500 hover:text-slate-300 transition-colors cursor-pointer">
          {copied ? 'Copie !' : 'Copier'}
        </button>
      </div>
      <pre className="text-[10px] font-mono text-slate-400 bg-slate-950 border border-slate-800/60 rounded p-3 overflow-x-auto whitespace-pre-wrap break-all leading-relaxed">{code}</pre>
    </div>
  )
}

export function IntegrationsTab({ apiUrl }: { apiUrl: string }) {
  const curlExample = `curl -H "Authorization: Bearer osiris_sk_..." \\
  ${apiUrl}/machines`

  const psExample = `$headers = @{ Authorization = "Bearer osiris_sk_..." }
$machines = Invoke-RestMethod "${apiUrl}/machines" -Headers $headers
$machines | Format-Table hostname, client, status`

  const pythonExample = `import requests

r = requests.get(
    "${apiUrl}/machines",
    headers={"Authorization": "Bearer osiris_sk_..."}
)
for m in r.json():
    print(m["hostname"], m["status"])`

  const webhookInExample = `POST ${apiUrl}/webhooks/new-machine
Authorization: Bearer osiris_sk_...
Content-Type: application/json

{
  "mac": "aa:bb:cc:dd:ee:ff",
  "hostname": "PC-DUPONT",
  "client": "Acme Corp",
  "os": "windows"
}`

  const grafanaExample = `# Plugin Grafana : Infinity Datasource
# URL : ${apiUrl}/machines
# Methode : GET
# Header : Authorization = Bearer osiris_sk_...
# Type : JSON
# Format : Table`

  const redeployExample = `# Redeclencher un deploiement (RMM, script cron...)
curl -X POST \\
  -H "Authorization: Bearer osiris_sk_..." \\
  ${apiUrl}/machines/aabbccddeeff/redeploy-now`

  const swaggerUrl = apiUrl.replace(/\/$/, '') + '/docs'

  return (
    <div className="p-6 space-y-5 overflow-y-auto" style={{ maxHeight: '70vh' }}>
      <div className="border-l-2 border-blue-800 pl-3 py-0.5 space-y-1">
        <p className="text-xs text-slate-300">Remplacez <code className="text-blue-400 text-[11px]">osiris_sk_...</code> par une cle API generee dans l'onglet "Cles API".</p>
        <a href={swaggerUrl} target="_blank" rel="noopener noreferrer"
          className="text-[10px] text-blue-500 hover:text-blue-400 transition-colors">
          Documentation interactive (Swagger) - {swaggerUrl}
        </a>
      </div>

      <div className="space-y-3">
        <p className="text-[9px] uppercase tracking-widest text-slate-600 font-semibold">Lecture - lister les machines</p>
        <CopyBlock label="curl / bash" code={curlExample} />
        <CopyBlock label="PowerShell (RMM, ConnectWise, N-central)" code={psExample} />
        <CopyBlock label="Python (script interne, Zabbix, Make)" code={pythonExample} />
      </div>

      <div className="space-y-3 pt-2 border-t border-slate-800/40">
        <p className="text-[9px] uppercase tracking-widest text-slate-600 font-semibold">Creation - pre-enregistrer une machine (GLPI, Jira, ticketing)</p>
        <p className="text-[10px] text-slate-600">Si la machine existe deja, aucune erreur - retour 200 avec les donnees existantes.</p>
        <CopyBlock label="Requete HTTP (GLPI webhook, Jira automation)" code={webhookInExample} />
      </div>

      <div className="space-y-3 pt-2 border-t border-slate-800/40">
        <p className="text-[9px] uppercase tracking-widest text-slate-600 font-semibold">Redeploiement - depuis un RMM ou un script</p>
        <CopyBlock label="curl" code={redeployExample} />
      </div>

      <div className="space-y-3 pt-2 border-t border-slate-800/40">
        <p className="text-[9px] uppercase tracking-widest text-slate-600 font-semibold">Grafana - Infinity Datasource</p>
        <CopyBlock label="Configuration Infinity Datasource" code={grafanaExample} />
      </div>

      <div className="pt-2 border-t border-slate-800/40 space-y-1">
        <p className="text-[9px] uppercase tracking-widest text-slate-600 font-semibold">Make / Zapier / n8n - webhook sortant</p>
        <p className="text-[10px] text-slate-500">
          Dans Administration &gt; Organisations, collez l'URL Make/Zapier/n8n dans le champ "Webhook URL".
          OSIRIS envoie automatiquement un JSON structure a chaque changement de statut :
          <code className="block text-[10px] font-mono mt-1 text-slate-400">event, hostname, mac, client, os, hw_model, hw_ram_gb, hw_serial, osiris_url</code>
        </p>
      </div>

      <div className="pt-2 border-t border-slate-800/40 space-y-1">
        <p className="text-[9px] uppercase tracking-widest text-slate-600 font-semibold">Snipe-IT / Lansweeper - export inventaire</p>
        <p className="text-[10px] text-slate-500">
          Endpoint CSV : <code className="text-slate-400">{apiUrl}/machines/export</code><br/>
          Contient : MAC, hostname, client, OS, profil, statut, modele, RAM, numero de serie, utilisateur, notes.
          A appeler depuis une tache planifiee ou le CMDB directement.
        </p>
      </div>
    </div>
  )
}

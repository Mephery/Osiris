#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Script OSIRIS de post-déploiement Windows. S'exécute au 1er démarrage.
    Appelé par unattend.xml (FirstLogonCommands) depuis le compte osiris-admin.
    Responsabilités :
      1. Attendre que le réseau soit disponible
      2. Envoyer le callback "deployed" à OSIRIS avec la vraie adresse MAC
      3. S'auto-supprimer
#>

$ErrorActionPreference = "Continue"
$logFile = "C:\osiris-firstboot.log"

function Write-Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

Write-Log "[OSIRIS] ===== Premier demarrage - post-deploiement ====="

# ── Lire la config OSIRIS depuis C:\osiris.cfg (écrit par le script WinPE) ───
$cfg      = Get-Content "C:\osiris.cfg" -ErrorAction SilentlyContinue
$m1       = $cfg | Select-String "^OSIRIS_URL=(.+)$"
$osiris   = if ($m1) { $m1.Matches.Groups[1].Value.Trim() } else { "" }
$m2       = $cfg | Select-String "^TV_SUFFIX=(.+)$"
$tvSuffix = if ($m2) { $m2.Matches.Groups[1].Value.Trim() } else { "" }
if (-not $osiris) {
    $gw = (Get-NetRoute -DestinationPrefix "0.0.0.0/0" | Sort-Object RouteMetric | Select-Object -First 1).NextHop
    $osiris = "http://${gw}:8000"
    Write-Log "[OSIRIS] osiris.cfg absent, heuristique gateway : $osiris"
} else {
    Write-Log "[OSIRIS] OSIRIS URL : $osiris"
}

# ── Attendre que le réseau soit up ────────────────────────────────────────────
Write-Log "[OSIRIS] Attente de la connectivite reseau..."
$retries = 0
while ($retries -lt 30) {
    try {
        $null = Invoke-WebRequest -Uri "$osiris/" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        break
    } catch {
        Start-Sleep -Seconds 5
        $retries++
    }
}

# ── Récupérer la vraie adresse MAC (premier adaptateur actif) ─────────────────
$adapter = Get-NetAdapter | Where-Object { $_.Status -eq "Up" -and $_.HardwareInterface } | Select-Object -First 1
if ($adapter) {
    $mac = $adapter.MacAddress -replace '-', '' | ForEach-Object { $_.ToLower() }
    Write-Log "[OSIRIS] MAC detectee : $mac"
} else {
    Write-Log "[OSIRIS] ERREUR : aucun adaptateur reseau actif"
    $mac = $null
}

# ── Callback "deployed" vers OSIRIS ──────────────────────────────────────────
if ($mac) {
    try {
        $resp = Invoke-WebRequest -Uri "$osiris/machines/$mac/status?status=deployed" `
            -Method POST -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
        Write-Log "[OSIRIS] Statut 'deployed' confirme (HTTP $($resp.StatusCode))"
    } catch {
        Write-Log "[OSIRIS] AVERTISSEMENT : callback echoue - $_"
    }
}

Write-Log "[OSIRIS] Post-deploiement termine."

# ── Configuration TeamViewer (si TV_SUFFIX défini dans le profil) ─────────────
# Prérequis : TeamViewer Host doit être installé dans la golden image.
# Mot de passe = NOMPC_EN_MAJUSCULES + tv_suffix (logique MSP : 1 suffixe par client)
if ($tvSuffix) {
    $tvPassword = "$($env:COMPUTERNAME.ToUpper())$tvSuffix"
    $tvExe = "C:\Program Files\TeamViewer\TeamViewer.exe"
    if (-not (Test-Path $tvExe)) {
        $tvExe = "C:\Program Files (x86)\TeamViewer\TeamViewer.exe"
    }
    if (Test-Path $tvExe) {
        # Accepter le CLUF via registre (les deux chemins selon version 32/64 bits)
        foreach ($p in @("HKLM:\SOFTWARE\TeamViewer", "HKLM:\SOFTWARE\WOW6432Node\TeamViewer")) {
            if (Test-Path $p) {
                Set-ItemProperty -Path $p -Name "LicenseAccepted" -Value 1 -Type DWord -ErrorAction SilentlyContinue
            }
        }
        # Définir le mot de passe d'accès
        & $tvExe --passwd $tvPassword | Out-Null
        Write-Log "[OSIRIS] TeamViewer : CLUF accepte, mot de passe defini ($($env:COMPUTERNAME.ToUpper())+***)"
    } else {
        Write-Log "[OSIRIS] AVERTISSEMENT : TeamViewer introuvable (a installer dans la golden image)"
    }
}

# ── Nettoyage : supprimer ce script ──────────────────────────────────────────
Start-Sleep -Seconds 2
Remove-Item -Path $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue

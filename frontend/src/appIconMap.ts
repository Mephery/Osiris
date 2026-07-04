// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
// Séparé de appIcons.tsx : ce fichier n'exporte que des composants (contrainte du Fast Refresh de Vite).
import {
  Logo7zip, LogoApache, LogoAudacity, LogoBitwarden, LogoCitrix, LogoDocker, LogoDotnet,
  LogoFirefox, LogoGooglechrome, LogoLibreoffice, LogoMariadb, LogoNetdata, LogoNextcloud,
  LogoNginx, LogoNotepadplusplus, LogoOpenjdk, LogoOpenvpn, LogoPostgresql, LogoRedis,
  LogoSignal, LogoTeamviewer, LogoVlcmediaplayer, LogoWireguard, LogoZoom,
} from './appIcons'

// Table de correspondance : nom d'app (Application.name en base) -> composant logo.
// Les apps absentes de cette table retombent sur l'emoji stocké en base (Application.icon).
export const APP_LOGOS: Record<string, React.FC<{ cls?: string }>> = {
  "7-Zip": Logo7zip,
  "Apache2": LogoApache,
  "Audacity": LogoAudacity,
  "Bitwarden": LogoBitwarden,
  "Citrix Workspace": LogoCitrix,
  "Docker": LogoDocker,
  ".NET Runtime 8": LogoDotnet,
  "Mozilla Firefox": LogoFirefox,
  "Google Chrome": LogoGooglechrome,
  "LibreOffice": LogoLibreoffice,
  "MariaDB": LogoMariadb,
  "Netdata": LogoNetdata,
  "Nextcloud Client": LogoNextcloud,
  "Nginx": LogoNginx,
  "Notepad++": LogoNotepadplusplus,
  "Java OpenJDK 21": LogoOpenjdk,
  "OpenVPN": LogoOpenvpn,
  "PostgreSQL": LogoPostgresql,
  "Redis": LogoRedis,
  "Signal": LogoSignal,
  "TeamViewer": LogoTeamviewer,
  "VLC": LogoVlcmediaplayer,
  "WireGuard": LogoWireguard,
  "Zoom": LogoZoom,
}

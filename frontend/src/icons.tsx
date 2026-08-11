// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.

type IProps = { cls?: string }

const S = ({ p, cls = 'w-3.5 h-3.5' }: { p: string; cls?: string }) => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"
    strokeLinecap="round" strokeLinejoin="round"
    className={`inline-block shrink-0 ${cls}`} aria-hidden="true">
    <path d={p} />
  </svg>
)

// Le scarabee de Khepri poussant un processeur a la place du disque solaire, la
// meme marque que `public/favicon.svg`. Etait un cercle a point, placeholder du
// premier jour.
//
// Format 32x24 et non carre, comme le favicon : les appelants doivent donc passer
// des dimensions au bon rapport (`w-8 h-6`), sinon la marque est mise en boite au
// milieu d'un carre et parait deux fois plus petite qu'elle ne l'est.
export const IcoOsiris    = ({ cls = 'w-8 h-6' }: IProps) => (
  <svg viewBox="0 0 32 24" fill="currentColor"
    className={`inline-block shrink-0 ${cls}`} aria-hidden="true">
    <defs>
    <mask id="osiris-c">
    <rect width="32" height="24" fill="#fff"/>
    <rect x="15.68" y="14.98" width="0.65" height="7.22" rx=".2" fill="#000"/>
    <rect x="14.21" y="9.85" width="0.53" height="1.61" rx=".14" fill="#000"/>
    <rect x="17.25" y="9.85" width="0.53" height="1.61" rx=".14" fill="#000"/>
    </mask>
    <mask id="osiris-a">
    <rect width="32" height="24" fill="#fff"/>
    <path d="M12.18 12.01L2.36 7.01" stroke="#000" strokeWidth="0.40" strokeLinecap="round"/>
    <path d="M12.01 12.73L0.99 12.92" stroke="#000" strokeWidth="0.40" strokeLinecap="round"/>
    <path d="M19.82 12.01L29.64 7.01" stroke="#000" strokeWidth="0.40" strokeLinecap="round"/>
    <path d="M19.99 12.73L31.01 12.92" stroke="#000" strokeWidth="0.40" strokeLinecap="round"/>
    </mask>
    </defs>
    <g mask="url(#osiris-a)">
    <ellipse cx="7.33" cy="11.27" rx="6.37" ry="4.13" transform="rotate(13 7.33 11.27)"/>
    <ellipse cx="24.67" cy="11.27" rx="6.37" ry="4.13" transform="rotate(-13 24.67 11.27)"/>
    </g>
    <path d="M13.34 11.94L10.96 10.23" stroke="currentColor" strokeWidth="1.10" strokeLinecap="round"/>
    <path d="M12.68 18.78L10.68 21.63" stroke="currentColor" strokeWidth="1.10" strokeLinecap="round"/>
    <path d="M18.66 11.94L21.04 10.23" stroke="currentColor" strokeWidth="1.10" strokeLinecap="round"/>
    <path d="M19.32 18.78L21.32 21.63" stroke="currentColor" strokeWidth="1.10" strokeLinecap="round"/>
    <g mask="url(#osiris-c)">
    <path d="M13.25 10.13H18.75L18.00 11.84H14.01Z"/>
    <ellipse cx="16.00" cy="13.18" rx="3.80" ry="2.18"/>
    <ellipse cx="16.00" cy="18.02" rx="3.99" ry="4.46"/>
    </g>
    <rect x="13.70" y="2.90" width="4.60" height="4.60" rx=".5"/>
    <rect x="12.75" y="3.38" width="0.95" height="0.69" rx=".18"/>
    <rect x="18.30" y="3.38" width="0.95" height="0.69" rx=".18"/>
    <rect x="14.18" y="1.95" width="0.69" height="0.95" rx=".18"/>
    <rect x="12.75" y="4.86" width="0.95" height="0.69" rx=".18"/>
    <rect x="18.30" y="4.86" width="0.95" height="0.69" rx=".18"/>
    <rect x="15.65" y="1.95" width="0.69" height="0.95" rx=".18"/>
    <rect x="12.75" y="6.33" width="0.95" height="0.69" rx=".18"/>
    <rect x="18.30" y="6.33" width="0.95" height="0.69" rx=".18"/>
    <rect x="17.13" y="1.95" width="0.69" height="0.95" rx=".18"/>
  </svg>
)
export const IcoDownload  = ({ cls = 'w-3.5 h-3.5' }: IProps) => <S cls={cls} p="M8 2v8m0 0L5 7m3 3 3-3M2 13h12" />
export const IcoRefresh   = ({ cls = 'w-3.5 h-3.5' }: IProps) => <S cls={cls} p="M14 8A6 6 0 1 1 8 2.5M14 2v4h-4" />
export const IcoSearch    = ({ cls = 'w-3.5 h-3.5' }: IProps) => <S cls={cls} p="M7 12A5 5 0 1 0 7 2a5 5 0 0 0 0 10zm7 2-3-3" />
export const IcoPower     = ({ cls = 'w-3.5 h-3.5' }: IProps) => <S cls={cls} p="M8 2v5M5 4A5 5 0 1 0 11 4" />
export const IcoPencil    = ({ cls = 'w-3.5 h-3.5' }: IProps) => <S cls={cls} p="M11 2l3 3-9 9H2v-3z" />
export const IcoX         = ({ cls = 'w-3.5 h-3.5' }: IProps) => <S cls={cls} p="M3 3l10 10M13 3 3 13" />
export const IcoCheck     = ({ cls = 'w-3.5 h-3.5' }: IProps) => <S cls={cls} p="M2 8l4 4 8-8" />
export const IcoChevDown  = ({ cls = 'w-3 h-3' }: IProps) => <S cls={cls} p="M3 5l5 5 5-5" />
export const IcoChevUp    = ({ cls = 'w-3 h-3' }: IProps) => <S cls={cls} p="M3 11l5-5 5 5" />
export const IcoChevRight = ({ cls = 'w-3 h-3' }: IProps) => <S cls={cls} p="M5 3l5 5-5 5" />
export const IcoGear      = ({ cls = 'w-4 h-4' }: IProps) => <S cls={cls} p="M8 5a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM1.5 8a6.5 6.5 0 1 1 13 0 6.5 6.5 0 0 1-13 0z" />
export const IcoTerminal  = ({ cls = 'w-3.5 h-3.5' }: IProps) => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"
    strokeLinecap="round" strokeLinejoin="round"
    className={`inline-block shrink-0 ${cls}`} aria-hidden="true">
    <rect x="1" y="2" width="14" height="11" rx="1.5" />
    <path d="M4 6.5l2.5 2-2.5 2M8.5 10.5h3.5" />
  </svg>
)
export const IcoCamera    = ({ cls = 'w-3.5 h-3.5' }: IProps) => <S cls={cls} p="M1 5h2l1.5-2h7L13 5h2v8H1zM8 12a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z" />

export const IcoSun = ({ cls = 'w-3.5 h-3.5' }: IProps) => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"
    strokeLinecap="round" className={`inline-block shrink-0 ${cls}`} aria-hidden="true">
    <circle cx="8" cy="8" r="3" />
    <path d="M8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3 3l1 1M12 12l1 1M13 3l-1 1M4 12l-1 1" />
  </svg>
)

export const IcoMoon = ({ cls = 'w-3.5 h-3.5' }: IProps) => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"
    strokeLinecap="round" strokeLinejoin="round"
    className={`inline-block shrink-0 ${cls}`} aria-hidden="true">
    <path d="M13.5 9.5A5.8 5.8 0 0 1 6.5 2.5a5.8 5.8 0 1 0 7 7Z" />
  </svg>
)

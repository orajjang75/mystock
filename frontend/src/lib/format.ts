const KO = 'ko-KR'

/** 12,345 (rounded). */
export function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-'
  return value.toLocaleString(KO, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

/** A KRW amount in the units Korean traders read: 3.5조, 482.0억, 9,500만. */
export function formatAmount(won: number | null | undefined): string {
  if (won === null || won === undefined || Number.isNaN(won)) return '-'
  const abs = Math.abs(won)
  if (abs >= 1e12) return `${(won / 1e12).toFixed(1)}조`
  if (abs >= 1e8) return `${(won / 1e8).toFixed(1)}억`
  if (abs >= 1e4) return `${formatNumber(Math.round(won / 1e4))}만`
  return formatNumber(won)
}

/** +1.23% / -0.50% / 0.00%. */
export function formatPercent(value: number | null | undefined, digits = 2, withSign = true): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-'
  const text = value.toFixed(digits)
  return withSign && value > 0 ? `+${text}%` : `${text}%`
}

/** ▲ 3.5 / ▼ 1.0 / - 0.0 for a change in score. */
export function formatChange(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-'
  const arrow = value > 0 ? '▲' : value < 0 ? '▼' : '–'
  return `${arrow} ${Math.abs(value).toFixed(digits)}`
}

export function formatScore(value: number | null | undefined): string {
  return value === null || value === undefined ? '-' : value.toFixed(1)
}

/** InputNumber helpers: show 291,546 while typing, and read it back without the commas. */
export const thousands = {
  formatter: (value: string | number | undefined) => `${value ?? ''}`.replace(/\B(?=(\d{3})+(?!\d))/g, ','),
  parser: (value: string | undefined) => Number((value ?? '').replace(/,/g, '')),
}

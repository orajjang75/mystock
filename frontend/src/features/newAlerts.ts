import type { AlertOut } from '../api/types'

const STORAGE_KEY = 'mystock.lastSeenAlertId'

export function readLastSeen(): number | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw === null ? null : Number(raw)
  } catch {
    return null
  }
}

export function writeLastSeen(id: number): void {
  try {
    localStorage.setItem(STORAGE_KEY, String(id))
  } catch {
    // not remembered; the next load just treats the current alerts as already seen
  }
}

/**
 * Which of the polled unread alerts are new since ``lastSeen``.
 *
 * With no ``lastSeen`` (first visit) nothing counts as new: the existing alerts are shown by the
 * badge, but they must not all pop up at once.
 */
export function detectNewAlerts(
  items: AlertOut[],
  lastSeen: number | null,
): { fresh: AlertOut[]; nextSeen: number } {
  const newest = items.reduce((max, alert) => Math.max(max, alert.id), lastSeen ?? 0)
  if (lastSeen === null) return { fresh: [], nextSeen: newest }
  const fresh = items.filter((alert) => alert.id > lastSeen).sort((a, b) => a.id - b.id)
  return { fresh, nextSeen: newest }
}

/** The one-line text of an alert for a notification or the banner. */
export function describeAlert(alert: AlertOut): string {
  const stock = alert.name ? ` ${alert.name}` : ''
  const quantity = alert.suggested_quantity ? ` · 제안 ${alert.suggested_quantity.toLocaleString('ko-KR')}주` : ''
  return `${alert.label}${stock}${quantity}`
}

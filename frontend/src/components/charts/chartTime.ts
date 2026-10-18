import type { Time } from 'lightweight-charts'

const KST_OFFSET_SECONDS = 9 * 3600

/**
 * Convert an API time label to a chart time.
 *
 * Daily bars come as "YYYY-MM-DD" and are used as is (a business day). Minute bars come as an
 * ISO timestamp with a +09:00 offset; Lightweight Charts draws UTC, so the Korea offset is added
 * to make the axis read in Korean local time.
 */
export function toChartTime(label: string): Time {
  if (label.length === 10) return label
  return (Math.floor(Date.parse(label) / 1000) + KST_OFFSET_SECONDS) as Time
}

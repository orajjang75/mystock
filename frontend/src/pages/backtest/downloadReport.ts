import { fetchBacktestReport } from '../../api/endpoints'

/** Save the report text of a run as a Markdown file in the browser. */
export async function downloadReport(id: number): Promise<void> {
  const text = await fetchBacktestReport(id)
  const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `backtest-${id}.md`
  link.click()
  URL.revokeObjectURL(url)
}

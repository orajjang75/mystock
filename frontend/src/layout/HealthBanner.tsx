import { Alert } from 'antd'
import { useHealth } from '../api/queries'

/** PRD 10장: stale or failed market data is shown at the top of every screen. */
export function HealthBanner() {
  const { data, isError } = useHealth()

  if (isError) {
    return <Alert banner type="error" message="서버에 연결할 수 없습니다. 표시된 값은 최신이 아닐 수 있습니다." />
  }
  if (data?.status === 'error') {
    return <Alert banner type="error" message="데이터베이스에 연결할 수 없습니다." />
  }
  if (!data) return null
  const paper = data.mode === 'paper'
  if (!paper && data.warnings.length === 0) return null
  return (
    <>
      {paper && (
        <Alert
          banner
          type="info"
          message="모의 운영 중 · 신호와 알림만 받습니다"
          description="체결 기록과 재매수 시도·사이클 포기는 받지 않습니다. 일별 리포트는 /api/ops/report 에서 봅니다."
        />
      )}
      {data.warnings.map((warning) => (
        <Alert
          key={warning.source}
          banner
          type="warning"
          message={`시세 갱신 지연 · ${warning.message}`}
          description="신호는 데이터가 다시 갱신될 때까지 만들어지지 않습니다."
        />
      ))}
    </>
  )
}

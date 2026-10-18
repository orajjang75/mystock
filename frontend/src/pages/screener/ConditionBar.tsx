import { Card, Space, Tag, Typography } from 'antd'
import dayjs from 'dayjs'
import type { ResultsResponse, SettingsResponse } from '../../api/types'
import { formatAmount } from '../../lib/format'

interface Props {
  settings: SettingsResponse | undefined
  results: ResultsResponse | undefined
}

const MODE_LABEL: Record<string, string> = {
  relaxed: '낙폭 기준 완화 적용',
  decline_rank: '하락률 순위 방식',
}

/** 조건 요약 바: the conditions a candidate has to meet, as currently set. */
export function ConditionBar({ settings, results }: Props) {
  const params = settings?.signal_params
  const gate = results?.gate as { mode?: string; drawdown_threshold_pct?: number | null } | null | undefined
  const mode = gate?.mode ?? 'strict'
  const drawdown = gate?.drawdown_threshold_pct ?? params?.screener.drawdown_threshold_pct

  return (
    <Card size="small" className="condition-bar" aria-label="조건 요약">
      <Space size={[8, 6]} wrap>
        <Typography.Text strong>조건 요약</Typography.Text>
        {params && (
          <>
            <Tag>거래대금 ≥ {formatAmount(params.screener.min_avg_trading_value)}</Tag>
            {mode === 'decline_rank' ? (
              <Tag color="orange">52주 낙폭이 큰 순서로 {params.scan.decline_rank_top_n}개</Tag>
            ) : (
              <Tag>
                52주 낙폭 ≤ {drawdown}% 그리고 (이격도 ≤ {params.screener.disparity_threshold_pct}% 또는 볼린저 하단 이탈{' '}
                {params.screener.bollinger_break_lookback}일)
              </Tag>
            )}
            <Tag>
              배점 반전 {params.score.reversal_points} · 확인 {params.score.confirmation_points} · 거래량{' '}
              {params.score.volume_points} · 수급 {params.score.flow_points}
            </Tag>
            <Tag>최소 점수 {params.scan.min_score}</Tag>
          </>
        )}
        {MODE_LABEL[mode] && <Tag color="orange">{MODE_LABEL[mode]}</Tag>}
        {results?.scan_date && (
          <Typography.Text type="secondary">
            스캔 일자 {dayjs(results.scan_date).format('YYYY-MM-DD')} · 결과 {results.items.length}종목
          </Typography.Text>
        )}
      </Space>
    </Card>
  )
}

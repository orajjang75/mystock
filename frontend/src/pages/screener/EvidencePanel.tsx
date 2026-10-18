import { Descriptions, Space, Tag, Typography } from 'antd'
import type { ResultItem } from '../../api/types'
import { formatAmount, formatNumber, formatPercent, formatScore } from '../../lib/format'
import { tagColor } from './tags'

type Evidence = Record<string, unknown>

const number = (evidence: Evidence, key: string): number | null => {
  const value = evidence[key]
  return typeof value === 'number' ? value : null
}

const fixed = (digits: number) => (value: number | null) => (value === null ? '-' : value.toFixed(digits))

// [key in the saved evidence, label, formatter]
const VALUES: [string, string, (value: number | null) => string][] = [
  ['drawdown_pct', '52주 고점 대비 낙폭', (v) => formatPercent(v, 1, false)],
  ['disparity_pct', '20일선 이격도', (v) => formatPercent(v, 1, false)],
  ['rsi', 'RSI(14)', fixed(1)],
  ['pct_b', '볼린저 %B', fixed(2)],
  ['macd_hist', 'MACD 히스토그램', fixed(2)],
  ['volume_ratio', '거래량 / 20일 평균', (v) => (v === null ? '-' : `${v.toFixed(2)}배`)],
  ['net_buy_strength_pct', '순매수 강도 (5일)', (v) => formatPercent(v, 2, false)],
  ['avg_trading_value', '20일 평균 거래대금', formatAmount],
  ['close', '종가', (v) => formatNumber(v)],
]

const SECTIONS: [string, string][] = [
  ['reversal', '반전'],
  ['confirmation', '확인'],
  ['volume', '거래량'],
  ['flow', '수급'],
]

interface Props {
  item: ResultItem
}

/** The indicator values behind a score (saved with the scan) and how the score splits up. */
export function EvidencePanel({ item }: Props) {
  const evidence = item.evidence as Evidence
  const breakdown = (evidence.breakdown ?? {}) as Record<string, number>

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <div>
        <Typography.Text strong>충족 조건</Typography.Text>
        <div style={{ marginTop: 6 }}>
          <Space size={[6, 6]} wrap>
            {item.tags.map((tag) => (
              <Tag key={tag.key} color={tagColor(tag.key)}>
                {tag.label}
              </Tag>
            ))}
          </Space>
        </div>
        {item.flow_unreflected && (
          <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
            이 날은 수급 데이터가 없어 수급 구간을 뺀 나머지 점수를 100점 기준으로 환산했습니다.
          </Typography.Paragraph>
        )}
      </div>

      <Descriptions
        size="small"
        column={{ xs: 1, sm: 2, lg: 3 }}
        bordered
        title="근거 지표 값"
        items={VALUES.map(([key, label, format]) => ({
          key,
          label,
          children: format(number(evidence, key)),
        }))}
      />

      <Descriptions
        size="small"
        column={{ xs: 2, sm: 4 }}
        bordered
        title={`점수 구성 (총 ${formatScore(item.score)}점)`}
        items={SECTIONS.map(([key, label]) => ({
          key,
          label,
          children: `${(breakdown[key] ?? 0).toFixed(1)}점`,
        }))}
      />
    </Space>
  )
}

import { Alert, Card, Radio, Space, Table, Typography } from 'antd'
import { useState } from 'react'
import { EChart } from '../../components/charts/EChart'
import type { SensitivityGrid } from '../../features/backtest/result'
import { GROUP_TITLES, PARAM_LABELS } from '../settings/paramLabels'
import { METRIC_LABELS, heatmapOption } from './chartOptions'
import { decimal } from './fmt'

interface GridRow {
  key: string
  y: number | null
  iy: number
}

const nameOf = (path: string) => `${GROUP_TITLES[path.split('.')[0]] ?? ''} · ${PARAM_LABELS[path]?.label ?? path}`

/** 파라미터 민감도 히트맵: pick the region that is good all around, not the single best cell. */
export function SensitivityTab({ grid }: { grid: SensitivityGrid }) {
  const [smoothed, setSmoothed] = useState(false)
  const best = smoothed ? grid.robust_best : grid.best
  const xs = grid.x.values
  const ys: (number | null)[] = grid.y?.values ?? [null]
  const rowsOf: GridRow[] = ys.map((y, iy) => ({ key: String(y), y, iy }))
  const describe = (pick: { x: number; y: number | null; value: number }) =>
    `${grid.x.path} = ${pick.x}${grid.y && pick.y !== null ? `, ${grid.y.path} = ${pick.y}` : ''} (${decimal(pick.value, 4)})`
  const empty = grid.cells.flat().every((v) => v === null)
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card
        size="small"
        title={`${METRIC_LABELS[grid.metric] ?? grid.metric} · ${grid.target === 'cycle' ? '사이클' : '신호 품질'}`}
        extra={
          <Radio.Group
            optionType="button"
            value={smoothed ? 'smooth' : 'raw'}
            onChange={(e) => setSmoothed(e.target.value === 'smooth')}
            options={[
              { value: 'raw', label: '칸별 값' },
              { value: 'smooth', label: '주변 3×3 평균' },
            ]}
          />
        }
      >
        <Typography.Paragraph type="secondary">
          가로 {nameOf(grid.x.path)} (기본 {grid.x.default})
          {grid.y && <>, 세로 {nameOf(grid.y.path)} (기본 {grid.y.default})</>}. 표본이 {grid.min_samples}건 미만인 칸은 비웠습니다.
        </Typography.Paragraph>
        {empty ? (
          <Alert type="warning" showIcon message="모든 칸이 표본 부족이라 보여 줄 값이 없습니다" />
        ) : (
          <EChart option={heatmapOption(grid, smoothed)} height={grid.y ? 120 + 56 * grid.y.values.length : 200} label="파라미터 민감도 히트맵" />
        )}
        <Space direction="vertical" size={2}>
          <Typography.Text>{smoothed ? '주변까지 고르게 좋은 칸' : '가장 높은 칸'}: {best ? describe(best) : '없음'} (굵은 테두리)</Typography.Text>
          {grid.best && grid.robust_best && (grid.best.x !== grid.robust_best.x || grid.best.y !== grid.robust_best.y) && (
            <Typography.Text type="warning">
              가장 높은 칸과 주변이 고른 칸이 다릅니다. 최고점 하나는 우연일 수 있으니 고른 칸 쪽을 더 믿으세요.
            </Typography.Text>
          )}
        </Space>
      </Card>
      <Card size="small" title="칸별 값과 표본">
        <Table
          size="small"
          pagination={false}
          rowKey="key"
          scroll={{ x: 520 }}
          dataSource={rowsOf}
          columns={[
            { title: grid.y ? `${grid.y.path} \\ ${grid.x.path}` : grid.x.path, render: (_: unknown, r: GridRow) => (r.y === null ? '-' : r.y) },
            ...xs.map((x, ix) => ({
              title: String(x),
              align: 'right' as const,
              render: (_: unknown, r: GridRow) => {
                const value = (smoothed ? grid.smoothed : grid.cells)[r.iy][ix]
                return value === null ? '-' : `${value.toFixed(4)} (n=${grid.samples[r.iy][ix]})`
              },
            })),
          ]}
        />
      </Card>
    </Space>
  )
}

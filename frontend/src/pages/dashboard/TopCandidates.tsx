import { Card, Empty, List, Space, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { useResults, useSparklines } from '../../api/queries'
import { Sparkline } from '../../components/charts/Sparkline'
import { Direction } from '../../components/Direction'
import { formatPercent, formatScore } from '../../lib/format'
import { tagColor } from '../screener/tags'

const TOP = 5

/** 오늘의 상위 후보 5개, each with a small trend line. */
export function TopCandidates() {
  const navigate = useNavigate()
  const results = useResults()
  const top = (results.data?.items ?? []).slice(0, TOP)
  const sparks = useSparklines(top.map((item) => item.code))

  return (
    <Card
      title="오늘의 상위 후보"
      extra={results.data?.scan_date && <Typography.Text type="secondary">{results.data.scan_date}</Typography.Text>}
      loading={results.isPending}
      size="small"
    >
      {top.length === 0 ? (
        <Empty description="스크리너에서 스캔을 실행하면 후보가 나타납니다" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <List
          dataSource={top}
          renderItem={(item, index) => {
            const closes = (sparks[index]?.data ?? []).map((c) => c.close)
            return (
              <List.Item
                style={{ cursor: 'pointer' }}
                onClick={() => navigate(`/screener?stock=${item.code}`)}
                actions={[<Sparkline key="spark" values={closes} />]}
              >
                <List.Item.Meta
                  avatar={<Typography.Text strong>{index + 1}</Typography.Text>}
                  title={
                    <Space wrap size={6}>
                      <span>{item.name}</span>
                      <Tag color="purple">{formatScore(item.score)}점</Tag>
                      <Direction value={item.change_pct}>{formatPercent(item.change_pct)}</Direction>
                    </Space>
                  }
                  description={
                    <Space size={[4, 4]} wrap>
                      {item.tags.slice(0, 3).map((tag) => (
                        <Tag key={tag.key} color={tagColor(tag.key)} style={{ marginInlineEnd: 0 }}>
                          {tag.label}
                        </Tag>
                      ))}
                      {item.tags.length > 3 && <Typography.Text type="secondary">+{item.tags.length - 3}</Typography.Text>}
                    </Space>
                  }
                />
              </List.Item>
            )
          }}
        />
      )}
    </Card>
  )
}

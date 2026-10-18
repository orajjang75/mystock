import { Card, Empty, List, Space, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { useWatchlist } from '../../api/queries'
import { Direction } from '../../components/Direction'
import { formatChange, formatScore } from '../../lib/format'

/** 관심종목 점수 변화: the latest score of each watched stock and its change since the last scan. */
export function WatchlistChanges() {
  const navigate = useNavigate()
  const watchlist = useWatchlist()
  const items = watchlist.data ?? []

  return (
    <Card title="관심종목 점수 변화" extra={<Typography.Text type="secondary">{items.length}종목</Typography.Text>} loading={watchlist.isPending} size="small">
      {items.length === 0 ? (
        <Empty description="스크리너 결과의 ★로 관심종목을 추가하세요" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <List
          dataSource={items}
          renderItem={(item) => (
            <List.Item style={{ cursor: 'pointer' }} onClick={() => navigate(`/screener?stock=${item.code}`)}>
              <List.Item.Meta title={item.name} description={item.code} />
              <Space size="middle">
                {item.score === null ? (
                  <Tag>{item.scan_date ? '게이트 미통과' : '스캔 없음'}</Tag>
                ) : (
                  <Typography.Text strong>{formatScore(item.score)}점</Typography.Text>
                )}
                <Direction value={item.change}>{formatChange(item.change)}</Direction>
              </Space>
            </List.Item>
          )}
        />
      )}
    </Card>
  )
}

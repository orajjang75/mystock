import { Col, Row } from 'antd'
import { PageHeader } from '../components/PageHeader'
import { HoldingCards } from './dashboard/HoldingCards'
import { RecentAlerts } from './dashboard/RecentAlerts'
import { SystemStatus } from './dashboard/SystemStatus'
import { TopCandidates } from './dashboard/TopCandidates'
import { WatchlistChanges } from './dashboard/WatchlistChanges'

export function DashboardPage() {
  return (
    <>
      <PageHeader title="대시보드" description="오늘의 상위 후보, 관심종목 점수 변화, 보유 종목 상태, 최근 알림을 한눈에 봅니다." />
      <Row gutter={[16, 16]}>
        <Col xs={24} xl={14}>
          <TopCandidates />
        </Col>
        <Col xs={24} xl={10}>
          <WatchlistChanges />
        </Col>
        <Col xs={24}>
          <HoldingCards />
        </Col>
        <Col xs={24} lg={14}>
          <RecentAlerts />
        </Col>
        <Col xs={24} lg={10}>
          <SystemStatus />
        </Col>
      </Row>
    </>
  )
}

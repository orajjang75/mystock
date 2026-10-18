import { App as AntdApp, Alert, Button, Popconfirm, Space } from 'antd'
import dayjs from 'dayjs'
import { errorMessage } from '../../api/client'
import { useAbandonCycle, useRetryCycle } from '../../api/queries'
import { formatNumber } from '../../lib/format'

interface Props {
  holdingId: number
  name: string
  cycleId: number
  rebuyTargetPrice: number
  expiresAt: string | null
  /** A compact button pair without the explanation (inside a list row). */
  compact?: boolean
}

/**
 * A-7: a rebuy wait that ran out. The user picks 재매수 시도 (wait for another window) or
 * 사이클 포기 (give up buying back). Nothing else happens until they choose.
 */
export function ExpiredActions({ holdingId, name, cycleId, rebuyTargetPrice, expiresAt, compact }: Props) {
  const { message } = AntdApp.useApp()
  const retry = useRetryCycle()
  const abandon = useAbandonCycle()
  const busy = retry.isPending || abandon.isPending

  const buttons = (
    <Space wrap>
      <Button
        type="primary"
        size={compact ? 'small' : 'middle'}
        loading={retry.isPending}
        disabled={busy}
        onClick={() =>
          retry.mutate(
            { holdingId, cycleId },
            {
              onSuccess: () => void message.success(`${name}: 재매수 대기를 다시 시작했습니다`),
              onError: (e) => void message.error(errorMessage(e)),
            },
          )
        }
      >
        재매수 시도
      </Button>
      <Popconfirm
        title="사이클을 포기할까요?"
        description="더 이상 재매수를 기다리지 않고 보유 상태로 돌아갑니다. 판 수량은 미회수로 남습니다."
        okText="포기"
        cancelText="취소"
        onConfirm={() =>
          abandon.mutate(
            { holdingId, cycleId },
            {
              onSuccess: () => void message.success(`${name}: 사이클을 포기했습니다`),
              onError: (e) => void message.error(errorMessage(e)),
            },
          )
        }
      >
        <Button size={compact ? 'small' : 'middle'} loading={abandon.isPending} disabled={busy}>
          사이클 포기
        </Button>
      </Popconfirm>
    </Space>
  )
  if (compact) return buttons

  return (
    <Alert
      type="warning"
      showIcon
      message="재매수 대기가 만료되었습니다"
      description={
        <Space direction="vertical" size={8}>
          <span>
            {expiresAt ? `${dayjs(expiresAt).format('MM-DD HH:mm')}까지` : '정해진 기간 안에'} 재매수 신호가 없었습니다. 재매수 목표가는{' '}
            {formatNumber(rebuyTargetPrice)}원이었습니다. 계속 기다릴지 포기할지 골라 주세요.
          </span>
          {buttons}
        </Space>
      }
    />
  )
}

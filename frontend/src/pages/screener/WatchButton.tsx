import { StarFilled, StarOutlined } from '@ant-design/icons'
import { App as AntdApp, Button, Tooltip } from 'antd'
import { errorMessage } from '../../api/client'
import { useToggleWatch } from '../../api/queries'

interface Props {
  code: string
  watched: boolean
}

/** The ★ that adds a stock to the watchlist or removes it. */
export function WatchButton({ code, watched }: Props) {
  const { message } = AntdApp.useApp()
  const toggle = useToggleWatch()

  return (
    <Tooltip title={watched ? '관심종목에서 제외' : '관심종목에 추가'}>
      <Button
        type="text"
        size="small"
        aria-label={watched ? `${code} 관심종목 제외` : `${code} 관심종목 추가`}
        aria-pressed={watched}
        loading={toggle.isPending}
        icon={watched ? <StarFilled style={{ color: '#faad14' }} /> : <StarOutlined />}
        onClick={(event) => {
          event.stopPropagation() // do not open the stock behind the row
          toggle.mutate({ code, watched }, { onError: (e) => void message.error(errorMessage(e)) })
        }}
      />
    </Tooltip>
  )
}

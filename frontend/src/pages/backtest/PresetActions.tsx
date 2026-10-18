import { App as AntdApp, Button, Input, Space, Typography } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { errorMessage } from '../../api/client'
import { useSaveBacktestPreset } from '../../api/queries'

interface Props {
  runId: number
  defaultName: string
}

/** 결과를 프리셋으로 저장하고, 원하면 스크리너와 알림이 쓰는 설정으로 바로 적용한다. */
export function PresetActions({ runId, defaultName }: Props) {
  const { message, modal } = AntdApp.useApp()
  const navigate = useNavigate()
  const save = useSaveBacktestPreset()
  const [name, setName] = useState(defaultName)

  const run = (apply: boolean) =>
    save.mutate(
      { id: runId, body: { name: name.trim() || null, apply } },
      {
        onSuccess: (result) => {
          void message.success(
            result.applied ? (
              <span>
                프리셋 "{result.name}"으로 저장하고 현재 설정에 적용했습니다. 다음 스캔부터 쓰입니다.{' '}
                {/* the message lives outside the router, so a Link would not work: navigate by hand */}
                <a
                  href="/screener"
                  onClick={(event) => {
                    event.preventDefault()
                    navigate('/screener')
                  }}
                >
                  스크리너로 이동
                </a>
              </span>
            ) : (
              `프리셋 "${result.name}"을 저장했습니다. 설정 화면에서 불러올 수 있습니다.`
            ),
          )
        },
        onError: (e) => void message.error(errorMessage(e)),
      },
    )

  const confirmApply = () =>
    modal.confirm({
      title: '스크리너에 적용할까요?',
      content: (
        <Typography.Text>
          현재 설정의 지표 파라미터와 신호 봉 길이가 이 실행의 값으로 바뀝니다. 스크리너와 보유 종목 알림이 다음 계산부터 이 값을 씁니다. 먼저 프리셋으로도 저장해 둡니다.
        </Typography.Text>
      ),
      okText: '적용',
      cancelText: '취소',
      onOk: () => run(true),
    })

  return (
    <Space.Compact style={{ maxWidth: 520, width: '100%' }}>
      <Input aria-label="프리셋 이름" value={name} maxLength={40} onChange={(e) => setName(e.target.value)} placeholder="프리셋 이름" />
      <Button loading={save.isPending} onClick={() => run(false)}>
        프리셋으로 저장
      </Button>
      <Button type="primary" loading={save.isPending} onClick={confirmApply}>
        스크리너에 적용
      </Button>
    </Space.Compact>
  )
}

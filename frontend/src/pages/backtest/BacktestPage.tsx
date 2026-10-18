import { Alert, App as AntdApp, Button, Card, Collapse, Space, Spin } from 'antd'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { errorMessage } from '../../api/client'
import { useBacktest, useBacktests, useCreateBacktest, useSettings } from '../../api/queries'
import { PageHeader } from '../../components/PageHeader'
import { BacktestForm } from './BacktestForm'
import { ResultView } from './ResultView'
import { RunList } from './RunList'

export function BacktestPage() {
  const { message } = AntdApp.useApp()
  const [params, setParams] = useSearchParams()
  const settings = useSettings()
  const runs = useBacktests()
  const create = useCreateBacktest()
  const selectedId = Number(params.get('run')) || runs.data?.[0]?.id
  const selected = useBacktest(selectedId)
  // The form starts open; once a run is started it folds away so the result is in view.
  const [formOpen, setFormOpen] = useState(true)

  const select = (id: number | null) => {
    const next = new URLSearchParams(params)
    if (id === null) next.delete('run')
    else next.set('run', String(id))
    setParams(next, { replace: true })
  }

  return (
    <>
      <PageHeader
        title="백테스트"
        description="스크리너와 알림이 쓰는 신호 코드를 그대로 과거 데이터에 돌려, 후보의 수익률과 수량 늘리기 사이클을 비용 반영해 검증합니다. 6장 기본값은 이 결과를 보고 직접 정하세요."
      />
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Collapse
          activeKey={formOpen ? ['new'] : []}
          onChange={(keys) => setFormOpen(keys.length > 0)}
          items={[
            {
              key: 'new',
              label: '새 백테스트',
              children: settings.data ? (
                <BacktestForm
                  settings={settings.data}
                  submitting={create.isPending}
                  onSubmit={(request) =>
                    create.mutate(request, {
                      onSuccess: (run) => {
                        select(run.id)
                        setFormOpen(false)
                        void message.success('백테스트를 시작했습니다')
                      },
                      onError: (e) => void message.error(errorMessage(e)),
                    })
                  }
                />
              ) : settings.isError ? (
                <Alert type="error" showIcon message="설정을 불러오지 못했습니다" action={<Button onClick={() => void settings.refetch()}>다시 시도</Button>} />
              ) : (
                <Spin />
              ),
            },
          ]}
        />
        <Card size="small" title="실행 목록">
          <RunList runs={runs.data ?? []} loading={runs.isPending} selectedId={selectedId} onSelect={select} />
        </Card>
        {selected.data && <ResultView key={selected.data.id} run={selected.data} onDeleted={() => select(null)} />}
        {selected.isError && <Alert type="error" showIcon message="실행 결과를 불러오지 못했습니다" description={errorMessage(selected.error)} />}
      </Space>
    </>
  )
}

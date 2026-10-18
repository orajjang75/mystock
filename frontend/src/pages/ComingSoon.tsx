import { Empty } from 'antd'
import { PageHeader } from '../components/PageHeader'

interface Props {
  title: string
  description: string
  step: string
}

export function ComingSoon({ title, description, step }: Props) {
  return (
    <>
      <PageHeader title={title} description={description} />
      <Empty description={`${step}에서 구현합니다`} style={{ marginTop: 64 }} />
    </>
  )
}

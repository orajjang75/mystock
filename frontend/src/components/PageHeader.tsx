import { Typography } from 'antd'
import type { ReactNode } from 'react'

interface Props {
  title: string
  description?: string
  extra?: ReactNode
}

export function PageHeader({ title, description, extra }: Props) {
  return (
    <div className="page-header">
      <div>
        <Typography.Title level={4} style={{ margin: 0 }}>
          {title}
        </Typography.Title>
        {description && <Typography.Text type="secondary">{description}</Typography.Text>}
      </div>
      {extra}
    </div>
  )
}

import { Form, InputNumber, Select, Button, Space, Collapse, Row, Col } from 'antd'
import { FilterOutlined, ClearOutlined } from '@ant-design/icons'
import { useState } from 'react'

interface FilterValues {
  priceMin?: number
  priceMax?: number
  premiumMin?: number
  premiumMax?: number
  dualLowMin?: number
  dualLowMax?: number
  volumeMin?: number
  remainingYearsMin?: number
  remainingYearsMax?: number
  sortBy?: string
  sortOrder?: 'asc' | 'desc'
}

interface FilterPanelProps {
  onChange: (filters: FilterValues) => void
}

const presetFilters: { label: string; value: FilterValues }[] = [
  { label: '双低策略', value: { dualLowMax: 140, premiumMax: 30 } },
  { label: '低溢价', value: { premiumMax: 10 } },
  { label: '高YTM', value: { sortBy: 'ytm', sortOrder: 'desc' } },
  { label: '活跃成交', value: { volumeMin: 1, sortBy: 'volume', sortOrder: 'desc' } },
  { label: '临期债', value: { remainingYearsMin: 0, remainingYearsMax: 1 } },
]

export default function FilterPanel({ onChange }: FilterPanelProps) {
  const [form] = Form.useForm()
  const [activeKey, setActiveKey] = useState<string[]>()
  const [currentPreset, setCurrentPreset] = useState<string>()

  const handleValuesChange = () => {
    const values = form.getFieldsValue()
    onChange(values)
  }

  const handleReset = () => {
    form.resetFields()
    setCurrentPreset(undefined)
    onChange({})
  }

  const handlePreset = (preset: { label: string; value: FilterValues }) => {
    form.resetFields()
    form.setFieldsValue(preset.value)
    onChange(preset.value)
  }

  return (
    <div style={{ marginBottom: 12 }}>
      <Space wrap style={{ marginBottom: 8 }}>
        <span style={{ fontWeight: 500 }}>快捷筛选:</span>
        {presetFilters.map((p) => (
          <Button
            key={p.label}
            size="small"
            type={currentPreset === p.label ? 'primary' : 'default'}
            onClick={() => {
              setCurrentPreset(p.label)
              handlePreset(p)
            }}
          >
            {p.label}
          </Button>
        ))}
      </Space>

      <Collapse
        activeKey={activeKey}
        onChange={(keys) => setActiveKey(keys as string[])}
        size="small"
        items={[
          {
            key: 'filter',
            label: (
              <Space>
                <FilterOutlined />
                高级筛选
              </Space>
            ),
            children: (
              <Form form={form} layout="inline" onValuesChange={handleValuesChange}>
                <Row gutter={[16, 8]}>
                  <Col span={4}>
                    <Form.Item label="价格" style={{ marginBottom: 8 }}>
                      <Space.Compact>
                        <Form.Item name="priceMin" noStyle>
                          <InputNumber placeholder="最低" size="small" style={{ width: 70 }} />
                        </Form.Item>
                        <Form.Item name="priceMax" noStyle>
                          <InputNumber placeholder="最高" size="small" style={{ width: 70 }} />
                        </Form.Item>
                      </Space.Compact>
                    </Form.Item>
                  </Col>
                  <Col span={4}>
                    <Form.Item label="溢价率%" style={{ marginBottom: 8 }}>
                      <Space.Compact>
                        <Form.Item name="premiumMin" noStyle>
                          <InputNumber placeholder="最低" size="small" style={{ width: 70 }} />
                        </Form.Item>
                        <Form.Item name="premiumMax" noStyle>
                          <InputNumber placeholder="最高" size="small" style={{ width: 70 }} />
                        </Form.Item>
                      </Space.Compact>
                    </Form.Item>
                  </Col>
                  <Col span={4}>
                    <Form.Item label="双低值" style={{ marginBottom: 8 }}>
                      <Space.Compact>
                        <Form.Item name="dualLowMin" noStyle>
                          <InputNumber placeholder="最低" size="small" style={{ width: 70 }} />
                        </Form.Item>
                        <Form.Item name="dualLowMax" noStyle>
                          <InputNumber placeholder="最高" size="small" style={{ width: 70 }} />
                        </Form.Item>
                      </Space.Compact>
                    </Form.Item>
                  </Col>
                  <Col span={3}>
                    <Form.Item name="volumeMin" label="成交额(亿)" style={{ marginBottom: 8 }}>
                      <InputNumber placeholder="最低" size="small" style={{ width: 80 }} />
                    </Form.Item>
                  </Col>
                  <Col span={3}>
                    <Form.Item name="remainingYearsMin" label="剩余年限" style={{ marginBottom: 8 }}>
                      <InputNumber placeholder="最低" size="small" style={{ width: 70 }} min={0} />
                    </Form.Item>
                  </Col>
                  <Col span={3}>
                    <Form.Item name="sortBy" label="排序" style={{ marginBottom: 8 }}>
                      <Select placeholder="选择" size="small" style={{ width: 100 }} allowClear>
                        <Select.Option value="price">价格</Select.Option>
                        <Select.Option value="change_pct">涨跌幅</Select.Option>
                        <Select.Option value="premium_ratio">溢价率</Select.Option>
                        <Select.Option value="dual_low">双低值</Select.Option>
                        <Select.Option value="volume">成交额</Select.Option>
                        <Select.Option value="ytm">YTM</Select.Option>
                      </Select>
                    </Form.Item>
                  </Col>
                  <Col span={2}>
                    <Form.Item name="sortOrder" style={{ marginBottom: 8 }}>
                      <Select placeholder="顺序" size="small" style={{ width: 70 }} allowClear>
                        <Select.Option value="asc">升序</Select.Option>
                        <Select.Option value="desc">降序</Select.Option>
                      </Select>
                    </Form.Item>
                  </Col>
                  <Col span={1}>
                    <Button icon={<ClearOutlined />} size="small" onClick={handleReset}>
                      重置
                    </Button>
                  </Col>
                </Row>
              </Form>
            ),
          },
        ]}
      />
    </div>
  )
}

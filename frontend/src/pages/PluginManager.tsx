/**
 * 插件管理页面
 */

import { useEffect, useState } from 'react'
import { Card, Tabs, List, Button, Space, Typography, Tag, Switch, Popconfirm, Modal, message, Empty, Row, Col, Statistic, Badge, Tooltip } from 'antd'
import { AppstoreOutlined, ShopOutlined, SettingOutlined, DeleteOutlined, DownloadOutlined, ReloadOutlined, CheckCircleOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import { getAvailablePlugins, getInstalledPlugins, installPlugin, uninstallPlugin, enablePlugin, disablePlugin, updatePlugin, type Plugin } from '../utils/pluginSystem'

const { Title, Text, Paragraph } = Typography

export default function PluginManager() {
  const [availablePlugins, setAvailablePlugins] = useState<Plugin[]>([])
  const [installedPlugins, setInstalledPlugins] = useState<Plugin[]>([])
  const [settingsModalVisible, setSettingsModalVisible] = useState(false)
  const [selectedPlugin, setSelectedPlugin] = useState<Plugin | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    loadPlugins()
  }, [])

  const loadPlugins = () => {
    setAvailablePlugins(getAvailablePlugins())
    setInstalledPlugins(getInstalledPlugins())
  }

  const handleInstall = async (id: string) => {
    setLoading(true)
    const success = await installPlugin(id)
    setLoading(false)

    if (success) {
      message.success('插件安装成功')
      loadPlugins()
    } else {
      message.error('插件安装失败')
    }
  }

  const handleUninstall = (id: string) => {
    if (uninstallPlugin(id)) {
      message.success('插件已卸载')
      loadPlugins()
    }
  }

  const handleToggle = (id: string, enabled: boolean) => {
    if (enabled) {
      enablePlugin(id)
    } else {
      disablePlugin(id)
    }
    loadPlugins()
  }

  const handleUpdate = async (id: string) => {
    const success = await updatePlugin(id)
    if (success) {
      message.success('插件已更新')
      loadPlugins()
    }
  }

  const PluginCard = ({ plugin, isInstalled }: { plugin: Plugin; isInstalled: boolean }) => (
    <List.Item
      actions={[
        isInstalled ? (
          <Space key="actions">
            <Switch
              checked={plugin.enabled}
              onChange={(checked) => handleToggle(plugin.id, checked)}
              checkedChildren="启用"
              unCheckedChildren="禁用"
            />
            <Button
              size="small"
              icon={<SettingOutlined />}
              onClick={() => {
                setSelectedPlugin(plugin)
                setSettingsModalVisible(true)
              }}
            >
              设置
            </Button>
            <Popconfirm
              title="确定卸载此插件？"
              onConfirm={() => handleUninstall(plugin.id)}
            >
              <Button size="small" danger icon={<DeleteOutlined />}>
                卸载
              </Button>
            </Popconfirm>
          </Space>
        ) : (
          <Button
            key="install"
            type="primary"
            size="small"
            icon={<DownloadOutlined />}
            onClick={() => handleInstall(plugin.id)}
            loading={loading}
          >
            安装
          </Button>
        ),
      ]}
    >
      <List.Item.Meta
        avatar={
          <div
            style={{
              width: 48,
              height: 48,
              borderRadius: 8,
              background: 'linear-gradient(135deg, #1890ff 0%, #722ed1 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <AppstoreOutlined style={{ color: '#fff', fontSize: 24 }} />
          </div>
        }
        title={
          <Space>
            <Text strong>{plugin.name}</Text>
            <Tag>v{plugin.version}</Tag>
            {plugin.hasUpdate && (
              <Badge status="processing" text="有更新" />
            )}
          </Space>
        }
        description={
          <Space direction="vertical" size={4}>
            <Text type="secondary">{plugin.description}</Text>
            <Space size={4}>
              <Text type="secondary">作者: {plugin.author}</Text>
              {plugin.permissions.length > 0 && (
                <Tooltip title={`所需权限: ${plugin.permissions.join(', ')}`}>
                  <ExclamationCircleOutlined style={{ color: '#faad14' }} />
                </Tooltip>
              )}
            </Space>
          </Space>
        }
      />
    </List.Item>
  )

  return (
    <div style={{ padding: 16, maxWidth: 1200, margin: '0 auto' }}>
      <Title level={4}>
        <AppstoreOutlined style={{ marginRight: 8 }} />
        插件管理
      </Title>

      {/* 统计信息 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card size="small">
            <Statistic
              title="已安装插件"
              value={installedPlugins.length}
              suffix="个"
              prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic
              title="已启用插件"
              value={installedPlugins.filter(p => p.enabled).length}
              suffix="个"
              prefix={<AppstoreOutlined style={{ color: '#1890ff' }} />}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic
              title="可用插件"
              value={availablePlugins.length}
              suffix="个"
              prefix={<ShopOutlined style={{ color: '#722ed1' }} />}
            />
          </Card>
        </Col>
      </Row>

      {/* 插件列表 */}
      <Card>
        <Tabs
          defaultActiveKey="installed"
          items={[
            {
              key: 'installed',
              label: (
                <Badge count={installedPlugins.length} offset={[10, 0]}>
                  已安装
                </Badge>
              ),
              children: installedPlugins.length > 0 ? (
                <List
                  itemLayout="horizontal"
                  dataSource={installedPlugins}
                  renderItem={(plugin) => <PluginCard plugin={plugin} isInstalled />}
                />
              ) : (
                <Empty description="暂无已安装的插件" />
              ),
            },
            {
              key: 'market',
              label: (
                <Badge count={availablePlugins.filter(p => !p.installed).length} offset={[10, 0]}>
                  插件市场
                </Badge>
              ),
              children: (
                <List
                  itemLayout="horizontal"
                  dataSource={availablePlugins.filter(p => !p.installed)}
                  renderItem={(plugin) => <PluginCard plugin={plugin} isInstalled={false} />}
                />
              ),
            },
            {
              key: 'updates',
              label: (
                <Badge count={installedPlugins.filter(p => p.hasUpdate).length} offset={[10, 0]}>
                  更新
                </Badge>
              ),
              children: installedPlugins.filter(p => p.hasUpdate).length > 0 ? (
                <List
                  itemLayout="horizontal"
                  dataSource={installedPlugins.filter(p => p.hasUpdate)}
                  renderItem={(plugin) => (
                    <List.Item
                      actions={[
                        <Button
                          key="update"
                          type="primary"
                          size="small"
                          icon={<ReloadOutlined />}
                          onClick={() => handleUpdate(plugin.id)}
                        >
                          更新到 v{plugin.latestVersion}
                        </Button>,
                      ]}
                    >
                      <List.Item.Meta
                        title={
                          <Space>
                            <Text strong>{plugin.name}</Text>
                            <Tag>v{plugin.version}</Tag>
                            <Text type="secondary">→ v{plugin.latestVersion}</Text>
                          </Space>
                        }
                        description={plugin.description}
                      />
                    </List.Item>
                  )}
                />
              ) : (
                <Empty description="暂无可用更新" />
              ),
            },
          ]}
        />
      </Card>

      {/* 插件设置弹窗 */}
      <Modal
        title={`${selectedPlugin?.name} 设置`}
        open={settingsModalVisible}
        onOk={() => setSettingsModalVisible(false)}
        onCancel={() => setSettingsModalVisible(false)}
        okText="保存"
        cancelText="取消"
      >
        {selectedPlugin && (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Paragraph>
              <Text strong>版本: </Text>
              {selectedPlugin.version}
            </Paragraph>
            <Paragraph>
              <Text strong>作者: </Text>
              {selectedPlugin.author}
            </Paragraph>
            <Paragraph>
              <Text strong>描述: </Text>
              {selectedPlugin.description}
            </Paragraph>
            {selectedPlugin.permissions.length > 0 && (
              <Paragraph>
                <Text strong>所需权限: </Text>
                {selectedPlugin.permissions.map(p => (
                  <Tag key={p}>{p}</Tag>
                ))}
              </Paragraph>
            )}
            <Text type="secondary">更多设置选项将在插件实现中定义</Text>
          </Space>
        )}
      </Modal>
    </div>
  )
}

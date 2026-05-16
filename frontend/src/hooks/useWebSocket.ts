import { useEffect, useRef, useState } from 'react'
import { notification } from 'antd'
import type { ConvertibleQuote } from '../types'
import { marketWs } from '../utils/wsInstances'

type MessageHandler = (bonds: ConvertibleQuote[]) => void
type ReconnectHandler = () => void

let marketReconnectCount = 0

export function useWebSocket(onMessage: MessageHandler, onReconnect?: ReconnectHandler) {
  const onMessageRef = useRef(onMessage)
  const onReconnectRef = useRef(onReconnect)
  const [isConnected, setIsConnected] = useState(marketWs.isConnected())
  const wasConnected = useRef(marketWs.isConnected())

  useEffect(() => {
    onMessageRef.current = onMessage
  }, [onMessage])

  useEffect(() => {
    onReconnectRef.current = onReconnect
  }, [onReconnect])

  useEffect(() => {
    const unsubMsg = marketWs.subscribe('tick', (data) => {
      onMessageRef.current(data as ConvertibleQuote[])
    })
    const unsubState = marketWs.onStateChange((state) => {
      const connected = state === 'connected'
      setIsConnected(connected)
      if (connected) {
        if (marketReconnectCount >= 3) {
          notification.success({ message: '行情 WebSocket 已重连', description: `经过 ${marketReconnectCount} 次重试后恢复连接`, duration: 5 })
        }
        marketReconnectCount = 0
        if (!wasConnected.current && onReconnectRef.current) {
          onReconnectRef.current()
        }
      } else if (state === 'reconnecting') {
        marketReconnectCount = marketWs.getAttemptCount()
        if (marketReconnectCount >= 3 && marketReconnectCount % 3 === 0) {
          notification.warning({ message: '行情连接异常', description: `已重试 ${marketReconnectCount} 次，请检查后端服务是否正常运行`, duration: 8 })
        }
      }
      wasConnected.current = connected
    })

    if (!marketWs.isConnected() && marketWs.getState() === 'disconnected') {
      marketWs.connect()
    }

    return () => {
      unsubMsg()
      unsubState()
    }
  }, [])

  return { isConnected }
}

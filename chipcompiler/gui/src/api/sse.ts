/**
 * SSE (Server-Sent Events) 客户端封装
 * 
 * 用于订阅后端推送的实时事件通知
 */

import { API_BASE_URL } from './client'

/**
 * SSE 通知类型
 */
export type NotifyType =
  | 'data_ready'      // 数据已就绪，可调用 get_info
  | 'step_start'      // step 开始执行
  | 'step_complete'   // step 执行完成
  | 'task_complete'   // 整个任务完成
  | 'error'           // 发生错误
  | 'heartbeat'       // 心跳保活
  | 'message'         // 通用消息

/**
 * SSE 通知数据结构
 */
export interface SSENotification {
  type: NotifyType
  step?: string
  id?: string
  message?: string
  timestamp: number
}

/**
 * SSE 事件处理器类型
 */
export type SSEEventHandler = (notification: SSENotification) => void

/**
 * SSE 客户端配置
 */
export interface SSEClientConfig {
  /** 自动重连，默认 true */
  autoReconnect?: boolean
  /** 重连延迟（毫秒），默认 1000 */
  reconnectDelay?: number
  /** 最大重连延迟（毫秒），默认 30000 */
  maxReconnectDelay?: number
  /** 连接超时时间（毫秒），默认 10000 */
  connectionTimeout?: number
}

/**
 * SSE 客户端状态
 */
export type SSEClientState = 'disconnected' | 'connecting' | 'connected' | 'error'

/**
 * 创建 SSE 客户端
 * 
 * @param taskId 任务 ID
 * @param config 客户端配置
 * @returns SSE 客户端实例
 * 
 * @example
 * ```typescript
 * const client = createSSEClient(taskId)
 * 
 * client.onStepStart((step) => {
 *   console.log(`Step ${step} started`)
 * })
 * 
 * client.onDataReady(async (step, id) => {
 *   const info = await api.getInfo({ step, id })
 *   updateUI(step, info)
 * })
 * 
 * client.onComplete(() => {
 *   console.log('Task completed')
 *   client.close()
 * })
 * 
 * client.connect()
 * ```
 */
export function createSSEClient(taskId: string, config: SSEClientConfig = {}) {
  const {
    autoReconnect = true,
    reconnectDelay = 1000,
    maxReconnectDelay = 30000,
  } = config

  let eventSource: EventSource | null = null
  let currentReconnectDelay = reconnectDelay
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let state: SSEClientState = 'disconnected'

  // 事件处理器映射
  const handlers = new Map<NotifyType, SSEEventHandler[]>()

  // 状态变更回调
  let stateChangeCallback: ((state: SSEClientState) => void) | null = null

  /**
   * 更新状态并触发回调
   */
  function setState(newState: SSEClientState) {
    state = newState
    stateChangeCallback?.(state)
  }

  /**
   * 连接到 SSE 事件流
   */
  function connect() {
    if (eventSource) {
      eventSource.close()
    }

    setState('connecting')

    const url = `${API_BASE_URL}/sse/stream/${taskId}`
    eventSource = new EventSource(url)

    // 监听所有事件类型
    const eventTypes: NotifyType[] = [
      'data_ready',
      'step_start',
      'step_complete',
      'task_complete',
      'error',
      'heartbeat',
      'message'
    ]

    for (const type of eventTypes) {
      eventSource.addEventListener(type, (e: MessageEvent) => {
        try {
          const notification: SSENotification = JSON.parse(e.data)
          // 重置重连延迟（连接正常）
          currentReconnectDelay = reconnectDelay

          // 触发对应类型的处理器
          const typeHandlers = handlers.get(type) || []
          typeHandlers.forEach(handler => {
            try {
              handler(notification)
            } catch (err) {
              console.error(`SSE handler error for ${type}:`, err)
            }
          })
        } catch (err) {
          console.error('SSE parse error:', err, e.data)
        }
      })
    }

    eventSource.onopen = () => {
      setState('connected')
      currentReconnectDelay = reconnectDelay
      console.log(`SSE connected to task: ${taskId}`)
    }

    eventSource.onerror = (e) => {
      console.error('SSE connection error:', e)
      setState('error')
      eventSource?.close()
      eventSource = null

      // 自动重连
      if (autoReconnect) {
        scheduleReconnect()
      }
    }
  }

  /**
   * 安排重连
   */
  function scheduleReconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
    }

    console.log(`SSE reconnecting in ${currentReconnectDelay}ms...`)

    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      connect()
    }, currentReconnectDelay)

    // 指数退避
    currentReconnectDelay = Math.min(
      currentReconnectDelay * 1.5,
      maxReconnectDelay
    )
  }

  /**
   * 关闭连接
   */
  function close() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }

    if (eventSource) {
      eventSource.close()
      eventSource = null
    }

    setState('disconnected')
    console.log(`SSE disconnected from task: ${taskId}`)
  }

  /**
   * 注册事件处理器
   */
  function on(type: NotifyType, handler: SSEEventHandler) {
    if (!handlers.has(type)) {
      handlers.set(type, [])
    }
    handlers.get(type)!.push(handler)
  }

  /**
   * 移除事件处理器
   */
  function off(type: NotifyType, handler: SSEEventHandler) {
    const typeHandlers = handlers.get(type)
    if (typeHandlers) {
      const index = typeHandlers.indexOf(handler)
      if (index !== -1) {
        typeHandlers.splice(index, 1)
      }
    }
  }

  return {
    /** 连接到 SSE 事件流 */
    connect,

    /** 关闭连接 */
    close,

    /** 注册事件处理器 */
    on,

    /** 移除事件处理器 */
    off,

    /** 获取当前状态 */
    getState: () => state,

    /** 监听状态变更 */
    onStateChange(callback: (state: SSEClientState) => void) {
      stateChangeCallback = callback
    },

    // ============ 便捷方法 ============

    /**
     * 监听数据就绪事件
     * 当收到此事件时，可以调用 get_info(step, id) 获取详细数据
     */
    onDataReady(callback: (step: string, id: string) => void) {
      on('data_ready', (n) => {
        if (n.step && n.id) {
          callback(n.step, n.id)
        }
      })
    },

    /**
     * 监听步骤开始事件
     */
    onStepStart(callback: (step: string) => void) {
      on('step_start', (n) => {
        if (n.step) {
          callback(n.step)
        }
      })
    },

    /**
     * 监听步骤完成事件
     */
    onStepComplete(callback: (step: string) => void) {
      on('step_complete', (n) => {
        if (n.step) {
          callback(n.step)
        }
      })
    },

    /**
     * 监听任务完成事件
     */
    onComplete(callback: (message?: string) => void) {
      on('task_complete', (n) => {
        callback(n.message)
      })
    },

    /**
     * 监听错误事件
     */
    onError(callback: (step: string | undefined, message: string) => void) {
      on('error', (n) => {
        callback(n.step, n.message || 'Unknown error')
      })
    },

    /**
     * 监听通用消息事件
     */
    onMessage(callback: (message: string) => void) {
      on('message', (n) => {
        if (n.message) {
          callback(n.message)
        }
      })
    },

    /**
     * 监听心跳事件
     */
    onHeartbeat(callback: () => void) {
      on('heartbeat', () => {
        callback()
      })
    }
  }
}

/**
 * SSE 客户端类型
 */
export type SSEClient = ReturnType<typeof createSSEClient>

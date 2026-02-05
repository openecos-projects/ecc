import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { useTauri } from './useTauri'
import { CMDEnum, StateEnum, StepEnum } from '@/api/type'
import { runStepApi, rtl2gdsApi, type RunStepResponse } from '@/api/flow'
import { createSSEClient, type SSEClient, type SSENotification } from '@/api/sse'

// ============ Composable ============

/**
 * 流程运行器 Hook
 * 负责处理流程的运行、停止、重置等操作
 */
export function useFlowRunner() {
  const { isInTauri, ensureTauri } = useTauri()
  const route = useRoute()

  // 状态
  const isRunning = ref(false)
  const state = ref<StateEnum>(StateEnum.Invalid)
  const error = ref<string | null>(null)
  const lastRunResult = ref<RunStepResponse | null>(null)

  /**
   * 获取当前步骤（从动态路由参数获取）
   */
  function getCurrentStep(): string | undefined {
    // 动态路由参数 :step
    const stepParam = route.params.step as string
    if (stepParam) {
      return stepParam
    }
  }

  /**
   * 运行当前步骤
   */
  async function runFlow(): Promise<RunStepResponse | null> {
    // 从动态路由参数获取当前步骤
    const step = getCurrentStep()

    if (!step) {
      console.warn('无法获取当前步骤')
      return null
    }

    // 检查是否在 Tauri 环境中
    if (!isInTauri) {
      console.warn('当前不在 Tauri 环境中，无法执行 Python 脚本')
      ensureTauri(true) // 显示警告弹窗
      return { step: step as StepEnum, state: StateEnum.Invalid }
    }

    if (isRunning.value) {
      return { step: step as StepEnum, state: StateEnum.Ongoing }
    }

    isRunning.value = true
    state.value = StateEnum.Ongoing
    error.value = null
    try {
      console.log('handleRunFlow', step)

      const result = await runStepApi({
        cmd: CMDEnum.run_step,
        data: {
          step: step as StepEnum,
          rerun: false
        }
      })
      console.log('run step result', result)
      return result.data
    } catch (err) {
      console.error('❌ 单步运行失败:', err)
    } finally {
      isRunning.value = false
    }
    return null
  }

  /**
   * 运行所有步骤
   * 
   * 1. 调用 rtl2gds API 获取 task_id
   * 2. 建立 SSE 连接订阅事件
   * 3. 实时接收进度通知
   */
  async function runAllFlow(): Promise<any | null> {
    // 检查是否在 Tauri 环境中
    if (!isInTauri) {
      console.warn('当前不在 Tauri 环境中，无法执行 Python 脚本')
      ensureTauri(true) // 显示警告弹窗
      return null
    }

    if (isRunning.value) {
      return null
    }

    // 如果已有 SSE 连接，先关闭
    if (sseClient.value) {
      sseClient.value.close()
      sseClient.value = null
    }

    isRunning.value = true
    state.value = StateEnum.Ongoing
    error.value = null
    sseMessages.value = []

    try {
      console.log('🚀 Starting rtl2gds flow...')

      // 1. 调用 rtl2gds API 获取 task_id
      const result = await rtl2gdsApi({
        cmd: CMDEnum.rtl2gds,
        data: {
          rerun: false
        }
      })
      console.log('rtl2gds API result:', result)

      const taskId = result.data?.task_id
      if (!taskId) {
        console.warn('No task_id returned from rtl2gds API')
        isRunning.value = false
        return result.data
      }

      sseTaskId.value = taskId
      console.log(`📡 Got task_id: ${taskId}`)

      // 2. 创建 SSE 客户端并订阅事件
      const client = createSSEClient(taskId)
      sseClient.value = client

      // 3. 注册事件处理器
      client.onStepStart((step) => {
        console.log(`▶️ Step started: ${step}`)
        sseMessages.value.push({
          type: 'step_start',
          step,
          timestamp: Date.now()
        })
      })

      client.onDataReady((step, id) => {
        console.log(`📦 Data ready: ${step}, id=${id}`)
        sseMessages.value.push({
          type: 'data_ready',
          step,
          id,
          timestamp: Date.now()
        })
      })

      client.onStepComplete((step) => {
        console.log(`✅ Step completed: ${step}`)
        sseMessages.value.push({
          type: 'step_complete',
          step,
          timestamp: Date.now()
        })
      })

      client.onMessage((message) => {
        console.log(`💬 Message: ${message}`)
        sseMessages.value.push({
          type: 'message',
          message,
          timestamp: Date.now()
        })
      })

      client.onComplete((message) => {
        console.log(`🎉 Task completed: ${message}`)
        sseMessages.value.push({
          type: 'task_complete',
          message,
          timestamp: Date.now()
        })
        // 任务完成后关闭连接
        isRunning.value = false
        state.value = StateEnum.Success
        client.close()
        sseClient.value = null
        sseTaskId.value = null
      })

      client.onError((step, message) => {
        console.error(`❌ Error in ${step}: ${message}`)
        sseMessages.value.push({
          type: 'error',
          step,
          message,
          timestamp: Date.now()
        })
        error.value = message
        isRunning.value = false
        state.value = StateEnum.Imcomplete
      })

      client.onHeartbeat(() => {
        // 心跳消息，不需要显示
      })

      // 4. 连接 SSE
      client.connect()
      console.log('📡 SSE client connected')

      return result.data
    } catch (err) {
      console.error('❌ 运行所有步骤失败:', err)
      error.value = err instanceof Error ? err.message : String(err)
      isRunning.value = false
      state.value = StateEnum.Imcomplete
    }
    return null
  }

  // SSE 相关状态
  const sseClient = ref<SSEClient | null>(null)
  const sseMessages = ref<SSENotification[]>([])
  const sseTaskId = ref<string | null>(null)

  return {
    // 状态
    isRunning,
    state,
    error,
    lastRunResult,

    // SSE 状态
    sseMessages,

    // 方法
    runFlow,
    runAllFlow
  }
}

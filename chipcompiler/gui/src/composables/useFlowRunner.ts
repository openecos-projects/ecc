import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { useTauri } from './useTauri'
import { CMDEnum, StateEnum, StepEnum } from '@/api/type'
import { runStepApi, rtl2gdsApi, type RunStepResponse } from '@/api/flow'

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

    isRunning.value = true
    state.value = StateEnum.Ongoing
    error.value = null
    try {
      console.log('handleRunAllFlow')

      const result = await rtl2gdsApi({
        cmd: CMDEnum.rtl2gds,
        data: {
          rerun: false
        }
      })
      console.log('run all flow result', result)
      return result.data
    } catch (err) {
      console.error('❌ 运行所有步骤失败:', err)
    } finally {
      isRunning.value = false
    }
    return null
  }

  /**
   * 停止当前流程
   */
  // async function stopFlow(): Promise<RunStepResponse> {
  //   if (!isRunning.value) {
  //     return { step: "", state: StateEnum.Invalid }
  //   }

  //   try {
  //     // TODO: 实现停止流程的逻辑
  //     console.log('Stopping flow...')

  //     isRunning.value = false
  //     state.value = StateEnum.Invalid

  //     return { step: "", state: StateEnum.Invalid }
  //   } catch (err) {
  //     console.error('❌ 单步运行停止失败:', err)
  //     return { step: "", state: StateEnum.Invalid }
  //   }
  // }

  /**
   * 重置流程状态
   */
  // async function resetFlow(): Promise<RunStepResponse> {
  //   try {
  //     // TODO: 实现重置流程的逻辑
  //     console.log('Resetting flow...')

  //     isRunning.value = false
  //     state.value = StateEnum.Invalid
  //     error.value = null
  //     lastRunResult.value = null

  //     return { step: "", state: StateEnum.Invalid }
  //   } catch (err) {
  //     const errorMessage = err instanceof Error ? err.message : String(err)
  //     error.value = errorMessage
  //     return { step: "", state: StateEnum.Invalid }
  //   }
  // }

  /**
   * 清除错误状态
   */
  function clearError(): void {
    error.value = null
  }

  return {
    // 状态
    isRunning,
    state,
    error,
    lastRunResult,

    // 方法
    runFlow,
    runAllFlow,
    // stopFlow,
    // resetFlow,
    clearError
  }
}

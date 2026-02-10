import { ref, watch, onMounted, onUnmounted } from 'vue'
import { readTextFile, readFile } from '@tauri-apps/plugin-fs'
import { invoke } from '@tauri-apps/api/core'
import { useWorkspace } from './useWorkspace'
import { useTauri } from './useTauri'

// ============ 类型定义 ============

/** home.json 数据结构 */
export interface HomeData {
  flow: string
  layout: string
  'GDS merge': string
  checklist: string
  metrics: Record<string, any>
  monitor: MonitorData
}

/** monitor 数据结构 */
export interface MonitorData {
  step: string[]
  memory: string[]
  runtime: string[]
  instance: number[]
  frequency: number[]
}

/** checklist.json 中的单个检查项 */
export interface ChecklistItem {
  step: string
  type: string
  item: string
  state: string
}

/** checklist.json 数据结构 */
export interface ChecklistData {
  path: string
  checklist: ChecklistItem[]
}

// ============ Composable ============

/**
 * Home 页面数据管理 Hook
 * 负责从 home.json 加载监控数据、checklist、layout 图片
 */
export function useHomeData() {
  const { isInTauri } = useTauri()
  const { currentProject } = useWorkspace()

  // 响应式数据
  const monitorData = ref<MonitorData | null>(null)
  const checklistItems = ref<ChecklistItem[]>([])
  const layoutBlobUrl = ref<string>('')
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  // 用于清理 blob URL
  let currentBlobUrl: string | null = null

  /**
   * 请求文件系统访问权限
   */
  async function requestPermission(path: string): Promise<boolean> {
    try {
      await invoke('request_project_permission', { path })
      return true
    } catch (permError) {
      console.warn('请求文件访问权限失败:', permError)
      return false
    }
  }

  /**
   * 将远程路径转换为本地项目路径
   * 例如: /nfs/share/home/xxx/benchmark/project_name/sub/path
   * 转换为: {projectPath}/sub/path
   */
  function convertToLocalPath(remotePath: string): string {
    if (!remotePath || !remotePath.includes('/nfs/')) {
      return remotePath
    }

    const projectPath = currentProject.value?.path
    if (!projectPath) {
      console.warn('No current project path available')
      return remotePath
    }

    // 从项目路径中提取项目名称（最后一个目录名）
    const projectName = projectPath.split(/[/\\]/).filter(Boolean).pop()
    if (!projectName) {
      console.warn('Cannot extract project name from path:', projectPath)
      return remotePath
    }

    // 在远程路径中找到项目名称的位置
    const projectNameIndex = remotePath.indexOf(`/${projectName}/`)
    if (projectNameIndex === -1) {
      console.warn('Project name not found in remote path:', remotePath)
      return remotePath
    }

    // 截取项目名称之后的相对路径部分
    const relativePath = remotePath.slice(projectNameIndex + projectName.length + 2)

    // 拼接本地项目路径
    const localPath = `${projectPath}/${relativePath}`
    console.log('Path converted:', remotePath, '->', localPath)

    return localPath
  }

  /**
   * 清理之前的 blob URL
   */
  function cleanupBlobUrl(): void {
    if (currentBlobUrl) {
      URL.revokeObjectURL(currentBlobUrl)
      currentBlobUrl = null
      layoutBlobUrl.value = ''
    }
  }

  /**
   * 加载 layout PNG 图片并转为 blob URL
   */
  async function loadLayoutImage(layoutPath: string): Promise<void> {
    if (!layoutPath) {
      cleanupBlobUrl()
      return
    }

    try {
      const localPath = convertToLocalPath(layoutPath)
      console.log('Loading layout image from:', localPath)

      const fileData = await readFile(localPath)
      const blob = new Blob([fileData], { type: 'image/png' })
      const blobUrl = URL.createObjectURL(blob)

      // 清理旧的 blob URL
      cleanupBlobUrl()

      currentBlobUrl = blobUrl
      layoutBlobUrl.value = blobUrl
      console.log('Layout blob URL created:', blobUrl)
    } catch (err) {
      console.error('Failed to load layout image:', err)
      cleanupBlobUrl()
    }
  }

  /**
   * 加载 checklist 数据
   */
  async function loadChecklist(checklistPath: string): Promise<void> {
    if (!checklistPath) {
      checklistItems.value = []
      return
    }

    try {
      const localPath = convertToLocalPath(checklistPath)
      console.log('Loading checklist from:', localPath)

      const fileContent = await readTextFile(localPath)
      const data: ChecklistData = JSON.parse(fileContent)

      checklistItems.value = data.checklist || []
      console.log('Checklist loaded:', checklistItems.value)
    } catch (err) {
      console.error('Failed to load checklist:', err)
      checklistItems.value = []
    }
  }

  /**
   * 从 home.json 加载所有 Home 页面数据
   */
  async function loadHomeData(): Promise<void> {
    if (!isInTauri || !currentProject.value?.path) {
      console.warn('无法加载 home.json: 不在 Tauri 环境或没有打开的项目')
      clearHomeData()
      return
    }

    isLoading.value = true
    error.value = null

    try {
      const projectPath = currentProject.value.path
      const homeJsonPath = `${projectPath}/home/home.json`
      console.log('Loading home.json from:', homeJsonPath)

      await requestPermission(projectPath)

      const fileContent = await readTextFile(homeJsonPath)
      const homeData: HomeData = JSON.parse(fileContent)

      console.log('Loaded home data:', homeData)

      // 加载 monitor 数据
      if (homeData.monitor) {
        monitorData.value = homeData.monitor
      }

      // 并行加载 checklist 和 layout
      await Promise.all([
        loadChecklist(homeData.checklist),
        loadLayoutImage(homeData.layout),
      ])

      console.log('Home data fully loaded')
    } catch (err) {
      console.error('Failed to load home.json:', err)
      error.value = err instanceof Error ? err.message : String(err)
      clearHomeData()
    } finally {
      isLoading.value = false
    }
  }

  /**
   * 重新加载所有数据
   */
  async function refreshHomeData(): Promise<void> {
    await loadHomeData()
  }

  /**
   * 清空所有数据
   */
  function clearHomeData(): void {
    monitorData.value = null
    checklistItems.value = []
    cleanupBlobUrl()
    error.value = null
  }

  // 监听当前项目变化，自动重新加载
  watch(
    () => currentProject.value?.path,
    async (newPath) => {
      if (newPath) {
        await loadHomeData()
      } else {
        clearHomeData()
      }
    },
    { immediate: true }
  )

  // 组件挂载时也尝试加载
  onMounted(async () => {
    if (currentProject.value?.path) {
      await loadHomeData()
    }
  })

  // 组件卸载时清理 blob URL
  onUnmounted(() => {
    cleanupBlobUrl()
  })

  return {
    // 状态
    monitorData,
    checklistItems,
    layoutBlobUrl,
    isLoading,
    error,

    // 方法
    loadHomeData,
    refreshHomeData,
    clearHomeData,
    convertToLocalPath,
  }
}

import { ref } from 'vue'
import type { Project, WorkspaceConfig } from '../types'
import { open } from '@tauri-apps/plugin-dialog'
import { invoke } from '@tauri-apps/api/core'
import { LazyStore } from '@tauri-apps/plugin-store'
import { exists } from '@tauri-apps/plugin-fs'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { loadWorkspaceApi, createWorkspaceApi } from '../api'
import { isTauri } from './useTauri'

// 序列化对象（将 Date 转换为 ISO 字符串）
interface SerializedProject {
  id: string
  name: string
  path: string
  lastOpened: string // 存储为 ISO 字符串
}

// 共享的状态实例（单例模式）
const store = new LazyStore('settings.json')
const currentProject = ref<Project | null>()
const recentProjects = ref<Project[]>([])

// 应用名称常量
const APP_NAME = 'ECC'

/**
 * 更新窗口标题
 * @param projectName 项目名称，为空时显示默认标题
 */
async function updateWindowTitle(projectName?: string) {
  if (!isTauri()) return

  try {
    const window = getCurrentWindow()
    const title = projectName ? `${projectName}` : APP_NAME
    await window.setTitle(title)
  } catch (error) {
    console.error('Failed to update window title:', error)
  }
}

export function useWorkspace() {


  /**
   * 路径标准化：处理跨平台路径分隔符，移除末尾斜杠
   */
  const normalizePath = (path: string): string => {
    // 统一使用正斜杠（Tauri 内部会自动处理平台差异）
    let normalized = path.replace(/\\/g, '/')
    // 移除末尾的斜杠
    if (normalized.endsWith('/') && normalized.length > 1) {
      normalized = normalized.slice(0, -1)
    }
    return normalized
  }

  /**
   * 序列化项目：将 Date 转换为 ISO 字符串
   */
  const serializeProject = (project: Project): SerializedProject => {
    return {
      ...project,
      path: normalizePath(project.path),
      lastOpened: project.lastOpened.toISOString()
    }
  }

  /**
   * 反序列化项目：将 ISO 字符串转换回 Date
   */
  const deserializeProject = (serialized: SerializedProject): Project => {
    return {
      ...serialized,
      lastOpened: new Date(serialized.lastOpened)
    }
  }

  /**
   * 检查项目路径是否仍然有效（文件夹是否存在）
   */
  const isProjectValid = async (path: string): Promise<boolean> => {
    try {
      return await exists(path)
    } catch (error) {
      console.error(`Failed to check path existence: ${path}`, error)
      return false
    }
  }

  /** 
   * loadRecentProjects 从本地加载最近项目，并执行失效检查
   */
  const loadRecentProjects = async () => {
    try {
      const savedProjects = await store.get<SerializedProject[]>('recent_projects')
      if (!savedProjects || savedProjects.length === 0) {
        return
      }

      // 反序列化并进行失效检查
      const validProjects: Project[] = []

      for (const serialized of savedProjects) {
        const project = deserializeProject(serialized)

        // 关键步骤：在检查路径之前，先请求 Rust 端授予访问权限
        try {
          await invoke('request_project_permission', { path: project.path })
        } catch (permError) {
          console.error(`请求访问权限失败: ${project.path}`, permError)
        }

        const isValid = await isProjectValid(project.path)

        if (isValid) {
          validProjects.push(project)
        } else {
          // 调试：看看为什么判定无效
          console.warn(`检测到无效路径: ${project.path}，暂时保留以防误删`);
          validProjects.push(project) // 开发阶段建议先保留
        }
      }

      recentProjects.value = validProjects

      // 如果 currentProject 为空且有有效项目，自动设置为第一项
      if (!currentProject.value && validProjects.length > 0) {
        currentProject.value = validProjects[0]
        // 更新窗口标题
        await updateWindowTitle(validProjects[0].name)
        console.log('Auto-set currentProject to:', validProjects[0].path)
      }

      // 如果清理后的列表和原列表不同，更新存储
      if (validProjects.length !== savedProjects.length) {
        const serialized = validProjects.map(serializeProject)
        await store.set('recent_projects', serialized)
        await store.save()
      }
    } catch (error) {
      console.error('Load recent projects error:', error)
    }
  }

  /**
   * 更新并保存最近项目
   */
  const addToRecent = async (project: Project) => {
    try {
      // 标准化路径
      const normalizedProject = {
        ...project,
        path: normalizePath(project.path)
      }

      // 去重：如果路径已存在，先删掉旧的
      const filtered = recentProjects.value.filter(
        p => normalizePath(p.path) !== normalizedProject.path
      )

      // 置顶：把最新的放到第一位
      recentProjects.value = [normalizedProject, ...filtered]

      // 限额：只保留最近 10 个
      if (recentProjects.value.length > 4) {
        recentProjects.value = recentProjects.value.slice(0, 4)
      }

      // 序列化并持久化到磁盘
      const serialized = recentProjects.value.map(serializeProject)
      await store.set('recent_projects', serialized)
      await store.save()

      return true
    } catch (error) {
      console.error('Add to recent error:', error)
      return false
    }
  }
  const openProject = async (project?: Project) => {
    try {
      let selectedPath: string | null = null

      if (project) {
        selectedPath = project.path
      } else {
        // 1. 弹出文件夹选择对话框
        const result = await open({
          directory: true,
          multiple: false,
          title: '选择 ECC 项目目录'
        })
        if (!result) return
        selectedPath = result as string
      }

      // 2. 请求 Rust 端动态授予该路径的访问权限（用于本地文件操作）
      try {
        await invoke('request_project_permission', { path: selectedPath })
      } catch (permError) {
        console.error('请求访问权限失败:', permError)
        // 权限请求失败不阻止继续，API 服务端有独立的文件访问权限
      }

      // 3. 通过 HTTP API 加载项目状态
      const response = await loadWorkspaceApi(selectedPath)
      if (response.response === 'success') {
        const loadedProject: Project = {
          id: response.data.directory,
          name: response.data.directory,
          path: response.data.directory,
          lastOpened: new Date()
        }

        currentProject.value = loadedProject

        // 更新窗口标题
        await updateWindowTitle(loadedProject.name)

        // 添加到最近项目列表（包含路径标准化和持久化）
        await addToRecent(loadedProject)

        return true
      } else {
        console.error('加载项目失败:', response.message)
        return false
      }
    } catch (error) {
      console.error('Open project error:', error)
      return false
    }
  }

  /**
   * 新建项目 - 支持 Wizard 配置
   * @param config 项目配置（来自向导）
   */
  const newProject = async (config?: WorkspaceConfig) => {
    try {
      let selectedPath: string

      if (config) {
        // 使用向导提供的配置
        selectedPath = config.directory
      } else {
        // 回退到旧的文件选择方式
        const result = await open({
          directory: true,
          multiple: false,
          title: '选择新项目保存位置'
        })

        if (!result) return false
        selectedPath = result as string
      }

      // 2. 请求 Rust 端动态授予该路径的访问权限（用于本地文件操作）
      try {
        await invoke('request_project_permission', { path: selectedPath })
      } catch (permError) {
        console.error('请求访问权限失败:', permError)
        // 权限请求失败不阻止继续，API 服务端有独立的文件访问权限
      }

      // 3. 通过 HTTP API 创建项目（传递更多配置信息）
      // 将前端参数映射为后端期望的格式 (参考 ics55_parameter.json)
      const frontendParams = config?.parameters || {}
      const pdkName = config?.pdk || 'ics55'
      const backendParameters = {
        // 基本设计信息 (必需)
        'Design': frontendParams.design || selectedPath.split('/').pop() || 'New_Chip_Design',
        'Top module': frontendParams.top_module || 'top',
        'Clock': frontendParams.clock || 'clk',
        'Frequency max [MHz]': frontendParams.frequency_max || 100,
        // PDK 信息
        'PDK': pdkName,
        // 核心配置
        'Core': {
          'Utilitization': frontendParams.core_utilization || 0.5
        },
        // 布局参数
        'Target density': frontendParams.target_density || 0.6,
        'Max fanout': frontendParams.max_fanout || 20
      }

      const response = await createWorkspaceApi({
        directory: selectedPath,
        pdk: pdkName,
        parameters: backendParameters,
        origin_def: config?.origin_def,
        origin_verilog: config?.origin_verilog,
        rtl_list: config?.rtl_list || ''
      })
      console.log(response)
      if (response.response === 'success') {
        const createdProject: Project = {
          id: response.data.directory,
          name: backendParameters['Design'] as string,
          path: response.data.directory,
          lastOpened: new Date()
        }

        currentProject.value = createdProject

        // 更新窗口标题
        await updateWindowTitle(createdProject.name)

        // 添加到最近项目列表（包含路径标准化和持久化）
        await addToRecent(createdProject)

        return true
      } else {
        console.error('创建项目失败:', response.message)
        return false
      }
    } catch (error) {
      console.error('New project error:', error)
      return false
    }
  }

  const importProject = () => {
    // 导入可以复用 openProject 的逻辑，或者针对不同格式做特殊处理
    openProject()
  }

  const closeProject = async () => {
    currentProject.value = null
    // 重置窗口标题为默认
    await updateWindowTitle()
  }

  return {
    loadRecentProjects,
    currentProject,
    recentProjects,
    openProject,
    newProject,
    importProject,
    closeProject,
    updateWindowTitle
  }
}

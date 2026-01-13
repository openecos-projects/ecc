import { ref } from 'vue'
import type { Project } from '../types'
import { open } from '@tauri-apps/plugin-dialog'
import { invoke } from '@tauri-apps/api/core'
import { LazyStore } from '@tauri-apps/plugin-store'
import { exists } from '@tauri-apps/plugin-fs'

// 序列化对象（将 Date 转换为 ISO 字符串）
interface SerializedProject {
  id: string
  name: string
  path: string
  lastOpened: string // 存储为 ISO 字符串
}

// 共享的状态实例（单例模式）
const store = new LazyStore('settings.json')
const currentProject = ref<Project | null>({
  id: '1',
  name: 'ics55_00001',
  path: '/Users/ekko/Desktop/ics55_00001',
  lastOpened: new Date()
})
const recentProjects = ref<Project[]>([])

export function useProject() {


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
        // 1. 【收信】弹出文件夹选择对话框
        const result = await open({
          directory: true,
          multiple: false,
          title: '选择 ECC 项目目录'
        })
        if (!result) return
        selectedPath = result as string
      }

      // 1.5 【授权】请求 Rust 端动态授予该路径的访问权限
      try {
        await invoke('request_project_permission', { path: selectedPath })
      } catch (permError) {
        console.error('请求访问权限失败:', permError)
        return false
      }

      // 2. 【发信】让 Python 加载项目状态
      const pyResult = await invoke('run_python', {
        script: 'test.py',
        args: ['--action', 'load', '--path', selectedPath]
      }) as { code: number, stdout: string, stderr: string }

      const response = JSON.parse(pyResult.stdout)

      if (pyResult.code === 0 && response.status === 'success') {
        const loadedProject: Project = {
          id: response.project.path,
          name: response.project.name,
          path: response.project.path,
          lastOpened: new Date()
        }

        currentProject.value = loadedProject

        // 添加到最近项目列表（包含路径标准化和持久化）
        await addToRecent(loadedProject)

        return true
      } else {
        console.error('加载项目失败:', response.message || pyResult.stderr)
        return false
      }
    } catch (error) {
      console.error('Open project error:', error)
      return false
    }
  }

  const newProject = async () => {
    try {
      // 1. 【收信】选择新项目存放的位置
      const selectedPath = await open({
        directory: true,
        multiple: false,
        title: '选择新项目保存位置'
      })

      if (!selectedPath) return

      // 1.5 【授权】请求 Rust 端动态授予该路径的访问权限
      try {
        await invoke('request_project_permission', { path: selectedPath as string })
      } catch (permError) {
        console.error('请求访问权限失败:', permError)
        return false
      }

      // 2. 【发信】初始化磁盘结构
      const projectName = 'New_Chip_Design'
      const pyResult = await invoke('run_python', {
        script: 'test.py',
        args: ['--action', 'init', '--path', selectedPath as string, '--name', projectName]
      }) as { code: number, stdout: string, stderr: string }

      const response = JSON.parse(pyResult.stdout)

      if (pyResult.code === 0 && response.status === 'success') {
        const createdProject: Project = {
          id: response.project.path,
          name: response.project.name,
          path: response.project.path,
          lastOpened: new Date()
        }

        currentProject.value = createdProject

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

  const closeProject = () => {
    currentProject.value = null
  }

  return {
    loadRecentProjects,
    currentProject,
    recentProjects,
    openProject,
    newProject,
    importProject,
    closeProject
  }
}


import { ref } from 'vue'
import type { Project } from '../types'

// 模拟的最近项目数据（后续可以从 localStorage 或 Tauri 读取）
const mockRecentProjects: Project[] = [
  {
    id: '1',
    name: '芯片设计项目 A',
    path: '~/Documents/Projects/chip-design-a',
    lastOpened: new Date(Date.now() - 1000 * 60 * 60 * 2) // 2小时前
  },
  {
    id: '2',
    name: 'FPGA 验证工程',
    path: '~/Documents/Projects/fpga-verification',
    lastOpened: new Date(Date.now() - 1000 * 60 * 60 * 24) // 1天前
  },
  {
    id: '3',
    name: 'IC 布局优化',
    path: '~/Documents/Projects/ic-layout',
    lastOpened: new Date(Date.now() - 1000 * 60 * 60 * 24 * 3) // 3天前
  }
]

// 共享的状态实例（单例模式）
const currentProject = ref<Project | null>(null)
const recentProjects = ref<Project[]>(mockRecentProjects)

export function useProject() {

  const openProject = (project?: Project) => {
    if (project) {
      currentProject.value = project
      // 更新最近打开时间
      project.lastOpened = new Date()
      // 移到列表最前面
      recentProjects.value = [
        project,
        ...recentProjects.value.filter(p => p.id !== project.id)
      ]
    } else {
      // TODO: 调用 Tauri API 打开文件选择器
      console.log('打开项目选择器...')
      // 临时模拟打开一个项目
      const newProject: Project = {
        id: Date.now().toString(),
        name: '新打开的项目',
        path: '~/Documents/new-project',
        lastOpened: new Date()
      }
      currentProject.value = newProject
      recentProjects.value.unshift(newProject)
    }
  }

  const newProject = () => {
    // TODO: 调用 Tauri API 创建新项目
    console.log('创建新项目...')
    const newProject: Project = {
      id: Date.now().toString(),
      name: '未命名项目',
      path: '~/Documents/untitled',
      lastOpened: new Date()
    }
    currentProject.value = newProject
    recentProjects.value.unshift(newProject)
  }

  const importProject = () => {
    // TODO: 调用 Tauri API 导入项目
    console.log('导入项目...')
  }

  const closeProject = () => {
    currentProject.value = null
  }

  return {
    currentProject,
    recentProjects,
    openProject,
    newProject,
    importProject,
    closeProject
  }
}


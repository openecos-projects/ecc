<template>
  <div class="flex flex-col h-full overflow-hidden">
    <!-- 自定义顶部栏 -->
    <TopBar />

    <!-- 欢迎页面内容 -->
    <WelcomePage :recent-projects="recentProjects" @open-project="handleOpenProject" @new-project="handleNewProject"
      @import-project="handleImportProject" @open-recent="handleOpenRecent" />
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import TopBar from '../components/TopBar.vue'
import WelcomePage from '../components/WelcomePage.vue'
import { useProject } from '../composables/useProject'
import type { Project } from '../types'

const router = useRouter()
const { recentProjects, openProject, newProject, importProject } = useProject()

const handleOpenProject = () => {
  openProject()
  router.push('/workspace')
}

const handleNewProject = () => {
  newProject()
  router.push('/workspace')
}

const handleImportProject = () => {
  importProject()
  router.push('/workspace')
}

const handleOpenRecent = (project: Project) => {
  openProject(project)
  router.push('/workspace')
}
</script>

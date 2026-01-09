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
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import TopBar from '../components/TopBar.vue'
import WelcomePage from '../components/WelcomePage.vue'
import { useProject } from '../composables/useProject'
import type { Project } from '../types'

const router = useRouter()
const { recentProjects, openProject, newProject, importProject, loadRecentProjects } = useProject()

const handleOpenProject = async () => {
  const success = await openProject()
  if (success) router.push('/workspace')
}

const handleNewProject = async () => {
  const success = await newProject()
  if (success) router.push('/workspace')
}

const handleImportProject = async () => {
  await importProject()
  router.push('/workspace')
}

const handleOpenRecent = async (project: Project) => {
  const success = await openProject(project)
  if (success) router.push('/workspace')
}

onMounted(async () => {
  await loadRecentProjects();
})
</script>

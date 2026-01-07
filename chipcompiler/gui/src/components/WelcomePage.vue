<template>
  <div
    class="flex flex-col items-center justify-center h-screen w-screen bg-(--bg-primary) text-(--text-primary) relative">
    <!-- 装饰性背景渐变 -->
    <div class="absolute inset-0 opacity-5 pointer-events-none welcome-gradient"></div>

    <div class="relative z-10 flex flex-col items-center w-full">
      <!-- Logo 和标题 -->
      <div class="flex items-center justify-center mb-12">
        <i class="ri-cpu-line text-6xl text-(--accent-color)"></i>
        <div class="flex flex-col ml-4">
          <h1 class="text-4xl font-bold mb-2 text-center text-(--text-primary)">ECOS Chip Compiler</h1>
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="flex gap-4 mb-16">
        <button @click="$emit('open-project')"
          class="flex flex-col items-center gap-3 px-8 py-6 bg-(--bg-secondary) hover:bg-(--bg-sidebar) rounded-lg transition-all hover:scale-105 border border-(--border-color) hover:border-(--accent-color) min-w-[160px]">
          <i class="ri-folder-open-line text-3xl text-(--text-primary)"></i>
          <span class="text-sm font-medium text-(--text-primary)">打开工程</span>
        </button>

        <button @click="$emit('new-project')"
          class="flex flex-col items-center gap-3 px-8 py-6 bg-(--bg-secondary) hover:bg-(--bg-sidebar) rounded-lg transition-all hover:scale-105 border border-(--border-color) hover:border-(--accent-color) min-w-[160px]">
          <i class="ri-add-circle-line text-3xl text-(--text-primary)"></i>
          <span class="text-sm font-medium text-(--text-primary)">新建工程</span>
        </button>

        <button @click="$emit('import-project')"
          class="flex flex-col items-center gap-3 px-8 py-6 bg-(--bg-secondary) hover:bg-(--bg-sidebar) rounded-lg transition-all hover:scale-105 border border-(--border-color) hover:border-(--accent-color) min-w-[160px]">
          <i class="ri-download-cloud-line text-3xl text-(--text-primary)"></i>
          <span class="text-sm font-medium text-(--text-primary)">导入工程</span>
        </button>
      </div>

      <!-- 最近项目 -->
      <div class="w-full max-w-3xl px-4">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-lg font-semibold text-(--text-primary)">最近的工程</h2>
          <button v-if="recentProjects.length > 5"
            class="text-sm text-(--accent-color) hover:opacity-80 transition-opacity">
            查看全部 ({{ recentProjects.length }})
          </button>
        </div>

        <div v-if="recentProjects.length === 0" class="text-center py-12 text-(--text-secondary)">
          <i class="ri-folder-2-line text-5xl mb-4 opacity-30"></i>
          <p>暂无最近打开的工程</p>
        </div>

        <div v-else class="space-y-2">
          <button v-for="project in recentProjects.slice(0, 5)" :key="project.id" @click="$emit('open-recent', project)"
            class="w-full flex items-center justify-between px-4 py-3 bg-(--bg-secondary) hover:bg-(--bg-sidebar) rounded-lg transition-colors border border-(--border-color) hover:border-(--accent-color) text-left group">
            <div class="flex items-center gap-3 flex-1 min-w-0">
              <i class="ri-folder-line text-xl text-(--accent-color)"></i>
              <div class="flex-1 min-w-0">
                <p class="font-medium text-(--text-primary) truncate">{{ project.name }}</p>
                <p class="text-sm text-(--text-secondary) truncate">{{ project.path }}</p>
              </div>
            </div>
            <span class="text-xs text-(--text-secondary) group-hover:text-(--text-primary) transition-colors">
              {{ formatDate(project.lastOpened) }}
            </span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Project } from '../types'

interface Props {
  recentProjects?: Project[]
}

interface Emits {
  (e: 'open-project'): void
  (e: 'new-project'): void
  (e: 'import-project'): void
  (e: 'open-recent', project: Project): void
}

withDefaults(defineProps<Props>(), {
  recentProjects: () => []
})

defineEmits<Emits>()

const formatDate = (date: Date) => {
  const now = new Date()
  const diff = now.getTime() - new Date(date).getTime()
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))

  if (days === 0) return '今天'
  if (days === 1) return '昨天'
  if (days < 7) return `${days} 天前`
  if (days < 30) return `${Math.floor(days / 7)} 周前`
  return new Date(date).toLocaleDateString('zh-CN')
}
</script>

<style scoped>
kbd {
  font-family: ui-monospace, monospace;
  font-size: 0.875em;
}

.welcome-gradient {
  background: radial-gradient(circle at 50% 50%, var(--accent-color) 0%, transparent 70%);
}
</style>

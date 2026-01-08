<template>
  <div
    class="h-10 bg-(--topbar-bg) flex items-center justify-between select-none border-b border-(--border-color) px-4">
    <!-- 左侧：应用图标和菜单栏 -->
    <div class="flex items-center h-full gap-6">
      <!-- 应用名称/图标 -->
      <div class="flex items-center gap-2">
        <i class="ri-cpu-line text-(--accent-color) text-xl"></i>
        <span class="font-bold text-sm text-(--topbar-text)">ECC</span>
      </div>

      <!-- 菜单项 -->
      <div class="flex items-center h-full gap-1">
        <button v-for="menu in menus" :key="menu.label" @click="handleMenuClick(menu.action)"
          class="h-full px-3 text-[13px] text-(--text-secondary) hover:text-(--text-primary) hover:bg-(--bg-secondary) transition-colors flex items-center justify-center rounded">
          {{ menu.label }}
        </button>
      </div>
    </div>

    <!-- 中间：项目信息 (可选) -->
    <div class="flex-1 flex items-center justify-center text-[13px] text-(--text-secondary)">
      <!-- 可以放置搜索框或者项目名称 -->
      {{ props.projectName }}
    </div>

    <!-- 右侧：设置和窗口控制 -->
    <div class="flex items-center h-full gap-2">
      <!-- 主题切换 -->
      <button @click="toggleTheme" class="p-2 text-(--text-secondary) hover:text-(--text-primary) transition-colors"
        title="切换主题">
        <i :class="isDark ? 'ri-sun-line' : 'ri-moon-line'" class="text-lg"></i>
      </button>
      <!-- <button class="p-2 text-(--text-secondary) hover:text-(--text-primary) transition-colors">
        <i class="ri-settings-4-line text-lg"></i>
      </button>
      <button class="p-2 text-(--text-secondary) hover:text-(--text-primary) transition-colors">
        <div class="w-6 h-6 bg-(--accent-color) rounded-full flex items-center justify-center text-white text-xs">
          U
        </div>
      </button> -->
    </div>

  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useThemeStore } from '@/stores/themeStore'

const props = defineProps<{
  projectName?: string
}>()

const themeStore = useThemeStore()
const isDark = computed(() => themeStore.themeName === 'dark')


// 切换主题
const toggleTheme = () => {
  themeStore.toggleTheme()
}

// 菜单项配置
const menus = [
  { label: 'File', action: 'file' },
  { label: 'Edit', action: 'edit' },
  { label: 'View', action: 'view' },
  { label: 'Run', action: 'run' },
  { label: 'Help', action: 'help' }
]

// 处理菜单点击
const handleMenuClick = (action: string) => {
  console.log('Menu clicked:', action)
}

// 监听窗口大小变化
onMounted(async () => {
  themeStore.initTheme()

})

// 组件卸载时清理监听
onUnmounted(() => { })
</script>

<style scoped>
/* 确保按钮图标垂直居中 */
button i {
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 响应式：在小屏幕上隐藏中间的项目名称 */
@media (max-width: 1630px) {
  .flex-1 {
    display: none;
  }
}
</style>

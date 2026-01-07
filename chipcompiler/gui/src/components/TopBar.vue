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

      <button class="p-2 text-(--text-secondary) hover:text-(--text-primary) transition-colors">
        <i class="ri-settings-4-line text-lg"></i>
      </button>
      <button class="p-2 text-(--text-secondary) hover:text-(--text-primary) transition-colors">
        <div class="w-6 h-6 bg-(--accent-color) rounded-full flex items-center justify-center text-white text-xs">
          U
        </div>
      </button>

      <!-- 窗口控制按钮 (Tauri - 仅在非 macOS 上显示) -->
      <div class="flex items-center h-full ml-4" v-if="isTauri && !isMacOS">
        <button @click="handleMinimize" :disabled="isProcessing"
          class="h-full px-3 text-(--text-secondary) hover:text-(--text-primary) hover:bg-(--bg-secondary) transition-colors flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed"
          title="最小化">
          <i class="ri-subtract-line"></i>
        </button>
        <button @click="handleMaximize" :disabled="isProcessing"
          class="h-full px-3 text-(--text-secondary) hover:text-(--text-primary) hover:bg-(--bg-secondary) transition-colors flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed"
          :title="isMaximized ? '还原' : '最大化'">
          <i :class="isMaximized ? 'ri-checkbox-multiple-blank-line' : 'ri-checkbox-blank-line'"></i>
        </button>
        <button @click="handleClose" :disabled="isProcessing"
          class="h-full px-3 text-(--text-secondary) hover:text-white hover:bg-red-500 transition-colors flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed"
          title="关闭">
          <i class="ri-close-line"></i>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useThemeStore } from '@/stores/themeStore'

const props = defineProps<{
  projectName?: string
}>()

const themeStore = useThemeStore()
const isDark = computed(() => themeStore.themeName === 'dark')

const isMaximized = ref(false)
const isTauri = ref(false)
const isMacOS = ref(false)
let unlistenResize: (() => void) | null = null
let isProcessing = ref(false) // 防止重复操作

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
  // TODO: 实现菜单功能
}

// 检查窗口是否最大化
const checkMaximized = async () => {
  if (!isTauri.value) return

  try {
    const { appWindow } = await import('@tauri-apps/api/window')
    isMaximized.value = await appWindow.isMaximized()
  } catch (error) {
    console.error('Error checking maximized state:', error)
  }
}

// 最小化窗口
const handleMinimize = async () => {
  if (!isTauri.value || isProcessing.value) return

  isProcessing.value = true
  try {
    const { appWindow } = await import('@tauri-apps/api/window')
    await appWindow.minimize()
  } catch (error) {
    console.error('Error minimizing window:', error)
  } finally {
    // 延迟重置，避免快速重复点击
    setTimeout(() => {
      isProcessing.value = false
    }, 300)
  }
}

// 最大化/还原窗口
const handleMaximize = async () => {
  if (!isTauri.value || isProcessing.value) return

  isProcessing.value = true
  try {
    const { appWindow } = await import('@tauri-apps/api/window')
    await appWindow.toggleMaximize()
    // macOS 上延迟检查状态
    if (isMacOS.value) {
      setTimeout(async () => {
        await checkMaximized()
      }, 100)
    } else {
      await checkMaximized()
    }
  } catch (error) {
    console.error('Error toggling maximize:', error)
  } finally {
    setTimeout(() => {
      isProcessing.value = false
    }, 300)
  }
}

// 关闭窗口
const handleClose = async () => {
  if (!isTauri.value || isProcessing.value) return

  isProcessing.value = true
  try {
    const { appWindow } = await import('@tauri-apps/api/window')
    await appWindow.close()
  } catch (error) {
    console.error('Error closing window:', error)
  }
  // 不需要重置 isProcessing，因为窗口会关闭
}

// 监听窗口大小变化
onMounted(async () => {
  themeStore.initTheme()

  // 检查是否在 Tauri 环境中
  isTauri.value = '__TAURI_IPC__' in window

  // 检测操作系统
  isMacOS.value = navigator.platform.toUpperCase().indexOf('MAC') >= 0

  if (!isTauri.value) {
    console.log('Running in browser mode (Tauri features disabled)')
    return
  }

  if (isMacOS.value) {
    console.log('Running on macOS - optimized window controls enabled')
  }

  await checkMaximized()

  // 监听窗口大小变化事件
  // macOS 上使用更长的防抖延迟
  let resizeTimeout: number | null = null
  const debounceDelay = isMacOS.value ? 200 : 100

  try {
    const { appWindow } = await import('@tauri-apps/api/window')
    unlistenResize = await appWindow.onResized(() => {
      if (resizeTimeout) clearTimeout(resizeTimeout)
      resizeTimeout = setTimeout(async () => {
        if (!isProcessing.value) {
          await checkMaximized()
        }
      }, debounceDelay)
    })
  } catch (error) {
    console.error('Error setting up resize listener:', error)
  }
})

// 组件卸载时清理监听
onUnmounted(() => {
  if (unlistenResize) {
    unlistenResize()
  }
})
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

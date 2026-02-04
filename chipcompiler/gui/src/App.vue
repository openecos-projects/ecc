<template>
  <div class="app-wrapper">
    <!-- 窗口调整大小的边缘区域 -->
    <div class="resize-edge resize-top" @mousedown="startResize('Top')"></div>
    <div class="resize-edge resize-bottom" @mousedown="startResize('Bottom')"></div>
    <div class="resize-edge resize-left" @mousedown="startResize('Left')"></div>
    <div class="resize-edge resize-right" @mousedown="startResize('Right')"></div>
    <div class="resize-corner resize-top-left" @mousedown="startResize('TopLeft')"></div>
    <div class="resize-corner resize-top-right" @mousedown="startResize('TopRight')"></div>
    <div class="resize-corner resize-bottom-left" @mousedown="startResize('BottomLeft')"></div>
    <div class="resize-corner resize-bottom-right" @mousedown="startResize('BottomRight')"></div>

    <!-- 主应用容器 -->
    <div class="app-container">
      <!-- 全局顶部菜单栏 -->
      <TopBar :project-name="currentProject?.name" />
      <!-- 页面内容 -->
      <router-view class="app-content" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { useThemeStore } from '@/stores/themeStore'
import { useWorkspace } from '@/composables/useWorkspace'
import TopBar from '@/components/TopBar.vue'

const themeStore = useThemeStore()
const { loadRecentProjects, currentProject } = useWorkspace()

// 窗口调整大小
type ResizeDirection = 'Top' | 'Bottom' | 'Left' | 'Right' | 'TopLeft' | 'TopRight' | 'BottomLeft' | 'BottomRight'

let isResizing = false

const startResize = async (direction: ResizeDirection) => {
  isResizing = true
  document.body.classList.add('window-resizing')
  const window = getCurrentWindow()
  await window.startResizeDragging(direction)
}

// 阻止拖拽调整窗口大小时的文本选择
const handleSelectStart = (e: Event) => {
  if (isResizing) {
    e.preventDefault()
    return false
  }
}

const handleMouseUp = () => {
  if (isResizing) {
    isResizing = false
    document.body.classList.remove('window-resizing')
  }
}

onMounted(async () => {
  themeStore.initTheme()
  // 在应用启动时加载最近项目，确保 currentProject 被初始化
  await loadRecentProjects()

  // 添加事件监听
  document.addEventListener('selectstart', handleSelectStart)
  document.addEventListener('mouseup', handleMouseUp)
})

onUnmounted(() => {
  document.removeEventListener('selectstart', handleSelectStart)
  document.removeEventListener('mouseup', handleMouseUp)
  document.body.classList.remove('window-resizing')
})
</script>

<style scoped>
.app-wrapper {
  width: 100%;
  height: 100%;
  position: relative;
}

.app-container {
  width: 100%;
  height: 100%;
  max-width: 100vw;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  /* 圆角窗口效果 */
  border-radius: 10px;
  background: var(--bg-primary);
  /* 边框 - 微弱的亮色边框 */
  border: 1px solid rgba(128, 128, 128, 0.3);
}

.app-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  background: var(--bg-primary);
}

/* 调整大小的边缘区域 */
.resize-edge,
.resize-corner {
  position: absolute;
  z-index: 9999;
}

/* 上边缘 */
.resize-top {
  top: 0;
  left: 20px;
  right: 20px;
  height: 6px;
  cursor: ns-resize;
}

/* 下边缘 */
.resize-bottom {
  bottom: 0;
  left: 20px;
  right: 20px;
  height: 6px;
  cursor: ns-resize;
}

/* 左边缘 */
.resize-left {
  left: 0;
  top: 20px;
  bottom: 20px;
  width: 6px;
  cursor: ew-resize;
}

/* 右边缘 */
.resize-right {
  right: 0;
  top: 20px;
  bottom: 20px;
  width: 6px;
  cursor: ew-resize;
}

/* 左上角 */
.resize-top-left {
  top: 0;
  left: 0;
  width: 20px;
  height: 20px;
  cursor: nwse-resize;
}

/* 右上角 */
.resize-top-right {
  top: 0;
  right: 0;
  width: 20px;
  height: 20px;
  cursor: nesw-resize;
}

/* 左下角 */
.resize-bottom-left {
  bottom: 0;
  left: 0;
  width: 20px;
  height: 20px;
  cursor: nesw-resize;
}

/* 右下角 */
.resize-bottom-right {
  bottom: 0;
  right: 0;
  width: 20px;
  height: 20px;
  cursor: nwse-resize;
}
</style>

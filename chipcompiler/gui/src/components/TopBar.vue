<template>
  <div class="topbar" @dblclick="handleDoubleClick">
    <!-- 左侧：应用图标和菜单栏 -->
    <div class="topbar-left">
      <!-- 应用图标 -->
      <div class="app-icon">
        <i class="ri-cpu-line"></i>
      </div>

      <!-- 菜单项 -->
      <div class="menu-items">
        <button v-for="menu in menus" :key="menu.label" @click="handleMenuClick(menu.action)" class="menu-btn">
          {{ menu.label }}
        </button>
      </div>
    </div>

    <div class="topbar-center" data-tauri-drag-region>
      <span class="project-name">{{ props.projectName }}</span>
    </div>

    <!-- 右侧：窗口控制按钮 -->
    <div class="topbar-right">
      <!-- 最小化 -->
      <button @click="handleMinimize" class="window-btn" title="最小化">
        <svg width="16" height="16" viewBox="0 0 16 16">
          <rect x="2" y="5.5" width="8" height="1" fill="currentColor" />
        </svg>
      </button>
      <!-- 最大化/还原 -->
      <button @click="handleMaximize" class="window-btn" title="最大化">
        <svg width="16" height="16" viewBox="0 0 16 16">
          <rect x="2" y="2" width="8" height="8" fill="none" stroke="currentColor" stroke-width="1" />
        </svg>
      </button>
      <!-- 关闭 -->
      <button @click="handleClose" class="window-btn window-btn-close" title="关闭">
        <svg width="16" height="16" viewBox="0 0 16 16">
          <path d="M3 3L9 9M9 3L3 9" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { invoke } from '@tauri-apps/api/core'

const props = defineProps<{
  projectName?: string
}>()

// 菜单项配置
const menus = [
  { label: 'File', action: 'file' },
  { label: 'Edit', action: 'edit' },
  { label: 'Selection', action: 'selection' },
  { label: 'View', action: 'view' },
  { label: 'Go', action: 'go' },
  { label: 'Run', action: 'run' },
  { label: 'Terminal', action: 'terminal' },
  { label: 'Help', action: 'help' }
]

// 处理菜单点击
const handleMenuClick = (action: string) => {
  console.log('Menu clicked:', action)
}

// 窗口控制
const handleMinimize = () => {
  invoke('window_minimize')
}

const handleMaximize = () => {
  invoke('window_maximize')
}

const handleClose = () => {
  invoke('window_close')
}

// 双击标题栏空白区域切换最大化/还原
const handleDoubleClick = (event: MouseEvent) => {
  const target = event.target as HTMLElement
  // 如果双击的是按钮或按钮内部元素，则不触发
  if (target.closest('button')) {
    return
  }
  invoke('window_maximize')
}
</script>

<style scoped>
.topbar {
  height: 40px;
  background: var(--topbar-bg);
  display: flex;
  align-items: center;
  justify-content: space-between;
  user-select: none;
  /* 圆角边框 */
  border-radius: 9px 9px 0 0;
  /* 底部分隔线 */
  border-bottom: 1px solid var(--border-color);
  /* 相对定位，用于中间区域的绝对定位 */
  position: relative;
}

/* 左侧区域 */
.topbar-left {
  display: flex;
  align-items: center;
  height: 100%;
  padding-left: 16px;
  gap: 8px;
  z-index: 1;
  position: relative;
}

.app-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  color: var(--accent-color);
  font-size: 18px;
}

.menu-items {
  display: flex;
  align-items: center;
  height: 100%;
  gap: 2px;
}

.menu-btn {
  height: 100%;
  padding: 0 10px;
  font-size: 13px;
  color: var(--text-secondary);
  background: transparent;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.15s, background-color 0.15s;
  border-radius: 4px;
}

.menu-btn:hover {
  color: var(--text-primary);
  background: var(--bg-secondary);
}

/* 中间拖拽区域 - 始终居中 */
.topbar-center {
  position: absolute;
  left: 50%;
  top: 0;
  transform: translateX(-50%);
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: auto;
  /* 不阻挡左右两侧的点击 */
  z-index: 0;
}

.project-name {
  font-size: 13px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  pointer-events: none;
}

/* 右侧窗口控制 */
.topbar-right {
  display: flex;
  align-items: center;
  height: 100%;
  z-index: 1;
  position: relative;
}

.window-btn {
  width: 46px;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  cursor: pointer;
  color: var(--text-secondary);
  transition: background-color 0.15s, color 0.15s;
}

.window-btn:hover {
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.window-btn-close {
  border-radius: 0 10px 0 0;
}

.window-btn-close:hover {
  background: #e81163;
  color: white;
}

/* 响应式：在小屏幕上隐藏中间的项目名称 */
@media (max-width: 900px) {
  .project-name {
    display: none;
  }
}
</style>

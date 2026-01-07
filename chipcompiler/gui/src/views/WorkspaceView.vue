<template>
  <div class="workspace-view">
    <!-- 自定义顶部栏 -->
    <TopBar :project-name="currentProject?.name" />

    <!-- 主内容区域 -->
    <main class="workspace-main">
      <!-- 最左侧工具栏  -->
      <LeftSidebar />

      <!-- 中间可调整面板 -->
      <Splitter class="flex-1 h-full border-none min-w-0">
        <SplitterPanel :size="65" :minSize="40" class="flex flex-col min-w-0">
          <Splitter layout="vertical" class="h-full border-none">
            <SplitterPanel :size="70" :minSize="30" class="flex flex-col">
              <DrawingArea />
            </SplitterPanel>
            <SplitterPanel :size="13" class="flex flex-col">
              <ThumbnailGallery />
            </SplitterPanel>
          </Splitter>
        </SplitterPanel>

        <SplitterPanel :size="35" :minSize="25" class="overflow-hidden min-w-0">
          <!-- AI Chat + Inspector 切换面板 -->
          <ChatInspectorPanel />
        </SplitterPanel>
      </Splitter>

      <!-- 最右侧属性栏 -->
      <RightSidebar />
    </main>
  </div>
</template>

<script setup lang="ts">
import Splitter from 'primevue/splitter'
import SplitterPanel from 'primevue/splitterpanel'
import TopBar from '../components/TopBar.vue'
import LeftSidebar from '../components/LeftSidebar.vue'
import DrawingArea from '../components/DrawingArea.vue'
import ChatInspectorPanel from '../components/ChatInspectorPanel.vue'
import RightSidebar from '../components/RightSidebar.vue'
import ThumbnailGallery from '../components/ThumbnailGallery.vue'
import { useProject } from '../composables/useProject'

const { currentProject } = useProject()
</script>

<style scoped>
.workspace-view {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  overflow: auto;
  background: var(--bg-primary);
  color: var(--text-primary);
}

.workspace-main {
  display: flex;
  flex: 1;
  overflow: hidden;
  position: relative;
  width: 100%;
  min-height: 0;
  /* 重要：防止 flex 子元素溢出 */
  min-width: 0;
  /* 允许 flex 子元素收缩 */
}

:deep(.p-splitter) {
  background: transparent;
  border: none;
  /* 优化性能 */
  contain: layout style;
}

:deep(.p-splitter-panel) {
  /* 优化重绘性能 */
  contain: layout style paint;
  will-change: auto;
}

:deep(.p-splitter-gutter) {
  background: var(--border-color);
  transition: background-color 0.15s ease-out;
  display: flex;
  align-items: center;
  justify-content: center;
  /* 减少重绘 */
  will-change: background-color;
}

:deep(.p-splitter-gutter:hover) {
  background: var(--accent-color);
  opacity: 0.5;
}

:deep(.p-splitter-gutter-handle) {
  display: none !important;
  /* 隐藏默认的大手柄 */
}

/* 针对横向分割条 */
:deep(.p-splitter-horizontal > .p-splitter-gutter) {
  width: 2px !important;
  cursor: col-resize;
}

/* 针对纵向分割条 */
:deep(.p-splitter-vertical > .p-splitter-gutter) {
  height: 2px !important;
  cursor: row-resize;
}

/* 确保 Splitter 面板可以正确收缩 */
:deep(.p-splitter-panel) {
  min-width: 0;
  overflow: hidden;
}

/* 响应式布局 - 在小屏幕上调整最小尺寸 */
@media (max-width: 1630px) {
  .workspace-main {
    /* 在小屏幕上允许更多的灵活性 */
    max-width: 100vw;
  }
}
</style>

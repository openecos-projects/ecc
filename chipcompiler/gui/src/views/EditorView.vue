<script setup lang="ts">
import Splitter from 'primevue/splitter'
import SplitterPanel from 'primevue/splitterpanel'
import DrawingArea from '../components/DrawingArea.vue'
import ChatInspectorPanel from '../components/ChatInspectorPanel.vue'
import ThumbnailGallery from '../components/ThumbnailGallery.vue'
</script>
<template>
  <div class="editor-view">
    <!-- 中间可调整面板 -->
    <Splitter class="flex-1 h-full border-none min-w-0">
      <SplitterPanel :size="65" :minSize="40" class="flex flex-col min-w-0">
        <Splitter layout="vertical" class="h-full border-none">
          <SplitterPanel :size="70" :minSize="30" class="flex flex-col">
            <DrawingArea />
          </SplitterPanel>
          <SplitterPanel :size="30" class="flex flex-col">
            <ThumbnailGallery />
          </SplitterPanel>
        </Splitter>
      </SplitterPanel>

      <SplitterPanel :size="35" :minSize="25" class="overflow-hidden min-w-0">
        <!-- AI Chat + Inspector 切换面板 -->
        <ChatInspectorPanel />
      </SplitterPanel>
    </Splitter>
  </div>
</template>
<style scoped>
.editor-view {
  width: 100%;
  height: 100%;
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
</style>
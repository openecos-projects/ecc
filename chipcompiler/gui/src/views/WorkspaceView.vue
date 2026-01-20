<template>
  <div class="workspace-view">
    <!-- 自定义顶部栏 -->
    <TopBar :project-name="currentProject?.name" />

    <!-- 主内容区域 -->
    <main class="workspace-main">
      <!-- 最左侧工具栏  -->
      <LeftSidebar />
      <router-view class="editor-view" />
      <!-- 最右侧属性栏 -->
      <!-- <RightSidebar /> -->
    </main>
  </div>
</template>

<script setup lang="ts">
import TopBar from '../components/TopBar.vue'
import LeftSidebar from '../components/LeftSidebar.vue'
// import RightSidebar from '../components/RightSidebar.vue'
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

.editor-view {
  width: 100%;
  height: 100%;
}

/* 响应式布局 - 在小屏幕上调整最小尺寸 */
@media (max-width: 1630px) {
  .workspace-main {
    /* 在小屏幕上允许更多的灵活性 */
    max-width: 100vw;
  }
}
</style>

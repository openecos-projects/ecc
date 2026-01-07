<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import { EditorContainer, type Editor } from '@/applications/editor'

const activeTool = ref('hand')
const isRulerEnabled = ref(true)
const zoomLevel = ref(100)
const editorRef = ref<InstanceType<typeof EditorContainer> | null>(null)
let unlistenTransform: (() => void) | null = null

const tools = [
  { id: 'hand', icon: 'ri-hand', tooltip: '平移' },
  { id: 'select', icon: 'ri-cursor-fill', tooltip: '选择' },
  { id: 'route', icon: 'ri-route-line', tooltip: '布线' }
]

const setActiveTool = (toolId: string) => {
  activeTool.value = toolId
}

const toggleRuler = () => {
  isRulerEnabled.value = !isRulerEnabled.value
  editorRef.value?.editor?.setPluginEnabled('ruler', isRulerEnabled.value)
}

const handleZoomIn = () => {
  editorRef.value?.editor?.zoomIn()
}

const handleZoomOut = () => {
  editorRef.value?.editor?.zoomOut()
}

const handleFitToWorld = () => {
  editorRef.value?.editor?.fitToWorld()
}

const onEditorReady = (editor: Editor) => {
  console.log('Editor ready:', editor)
  // 确保编辑器标尺状态与 UI 同步
  editor.setPluginEnabled('ruler', isRulerEnabled.value)

  // 监听缩放变化更新 UI
  zoomLevel.value = Math.round(editor.getScale() * 100)
  unlistenTransform = editor.onTransformChange((t) => {
    zoomLevel.value = Math.round(t.scale * 100)
  })
}

onUnmounted(() => {
  if (unlistenTransform) {
    unlistenTransform()
  }
})
</script>

<template>
  <div class="flex flex-col h-full overflow-hidden">
    <!-- 顶部工具栏 -->
    <div class="h-10 bg-(--bg-secondary) border-b border-(--border-color) flex items-center gap-2 px-4 shrink-0">
      <!-- 工具按钮组 -->
      <div class="flex items-center gap-1">
        <button v-for="tool in tools" :key="tool.id" @click="setActiveTool(tool.id)" :class="{
          'bg-(--accent-color) text-white': activeTool === tool.id,
          'text-(--text-secondary) hover:text-(--text-primary) hover:bg-(--bg-hover)': activeTool !== tool.id
        }" class="w-9 h-9 flex items-center justify-center rounded transition-all" :title="tool.tooltip">
          <i :class="tool.icon" class="text-base"></i>
        </button>
      </div>

      <div class="w-px h-6 bg-(--border-color)"></div>

      <!-- 右侧：缩放控制等 -->
      <div class="flex-1 flex items-center justify-end gap-3">
        <!-- 标尺开关 -->
        <button @click="toggleRuler" :class="[
          isRulerEnabled ? 'text-(--accent-color) bg-(--accent-color)/10 border-(--accent-color)/20' : 'text-(--text-secondary) border-transparent hover:bg-(--bg-hover)',
          'h-8 px-2 flex items-center gap-1.5 rounded border transition-all'
        ]" title="显示/隐藏标尺">
          <i class="ri-ruler-line text-base"></i>
        </button>

        <div class="w-px h-6 bg-(--border-color)"></div>

        <div class="flex items-center gap-2 px-3 py-1.5 bg-(--bg-primary) rounded border border-(--border-color)">
          <button @click="handleZoomOut" class="text-(--text-secondary) hover:text-(--text-primary) transition-colors"
            title="缩小">
            <i class="ri-subtract-line text-sm"></i>
          </button>
          <span class="text-[13px] text-(--text-primary) font-medium min-w-[50px] text-center">{{ zoomLevel }}%</span>
          <button @click="handleZoomIn" class="text-(--text-secondary) hover:text-(--text-primary) transition-colors"
            title="放大">
            <i class="ri-add-line text-sm"></i>
          </button>
        </div>
        <button @click="handleFitToWorld"
          class="w-8 h-8 flex items-center justify-center rounded text-(--text-secondary) hover:text-(--text-primary) hover:bg-(--bg-hover) transition-colors"
          title="适应画布">
          <i class="ri-fullscreen-fill text-base"></i>
        </button>
      </div>
    </div>

    <!-- 编辑器容器 -->
    <div class="relative flex-1 overflow-hidden">
      <EditorContainer ref="editorRef" @ready="onEditorReady" />
    </div>
  </div>
</template>

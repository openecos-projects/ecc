<script setup lang="ts">
import { shallowRef, watch } from 'vue'
import { useRoute } from 'vue-router'
import { EditorContainer, type Editor } from '@/applications/editor'
import DrawingToolbar from './DrawingToolbar.vue'
import { useProject } from '@/composables/useProject'

const route = useRoute()
const { currentProject } = useProject()

const editor = shallowRef<Editor | null>(null)

const onEditorReady = (editorInstance: Editor) => {
  console.log('Editor ready:', editorInstance)
  editor.value = editorInstance

  // 初始加载当前路径对应的数据
  const pathParts = route.path.split('/')
  const stage = pathParts[pathParts.length - 1] || 'home'
  handleStageChange(stage)
}

/**
 * 处理阶段切换，加载对应的 EDA 结果
 */
const handleStageChange = async (stage: string) => {
  console.log('handleStageChange:', stage)
  console.log('currentProject.value:', currentProject.value)
  if (!editor.value || !currentProject.value || !stage) return

  // 映射前端路径名到 EDA 逻辑中的步骤名
  const stageMap: Record<string, string> = {
    'floorplan': 'Floorplan',
    'place': 'Placement',
    'cts': 'CTS',
    'route': 'Routing'
  }
  const edaStep = stageMap[stage]
  if (!edaStep) {
    editor.value.clearBackground()
    return
  }

  console.log(`Loading EDA results for stage: ${stage} (${edaStep})`)

  try {
    // 1.调用接口获取数据
    const res = null; // TODO: 调用接口获取数据


    // if (res.status === 'success' && res.payload?.exists) {
    //   // 2. 转换为可访问的 URL (现在是异步的)
    //   const imgUrl = await getResourceUrl(res.payload.image_path, currentProject.value.path)
    //   // 3. 更新编辑器背景（会自动调用fit进行适应）
    //   await editor.value.setBackgroundImage(imgUrl)
    // } else {
    //   console.warn('No visual result for this stage:', res.message || 'File not found')
    //   editor.value.clearBackground()
    // }
  } catch (error) {
    console.error('Failed to load stage results:', error)
  }
}

// 监听路由路径变化
watch(() => route.path, (newPath) => {
  const pathParts = newPath.split('/')
  const stage = pathParts[pathParts.length - 1] || 'home'
  console.log('route.path changed to:', stage)
  handleStageChange(stage)
})
</script>

<template>
  <div class="flex flex-col h-full overflow-hidden">
    <!-- 顶部工具栏 -->
    <DrawingToolbar :editor="editor" />

    <!-- 编辑器容器 -->
    <div class="relative flex-1 overflow-hidden">
      <EditorContainer @ready="onEditorReady" />
    </div>
  </div>
</template>

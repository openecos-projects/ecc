<script setup lang="ts">
import { shallowRef } from 'vue'
import { EditorContainer, type Editor } from '@/applications/editor'
import DrawingToolbar from './DrawingToolbar.vue'

const editor = shallowRef<Editor | null>(null)

const onEditorReady = (editorInstance: Editor) => {
  console.log('Editor ready:', editorInstance)
  editor.value = editorInstance
}
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

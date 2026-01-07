<template>
  <div class="flex h-full">
    <!-- 标签切换栏 -->
    <div class="w-12 bg-(--bg-sidebar) border-l border-(--border-color) flex flex-col items-center py-3 gap-3">
      <button @click="activeTab = 'chat'" :class="[
        'w-9 h-9 rounded flex items-center justify-center transition-all',
        activeTab === 'chat'
          ? 'bg-(--accent-color) text-white shadow-sm'
          : 'text-(--text-secondary) hover:text-(--accent-color) hover:bg-(--bg-secondary)'
      ]" title="AI Chat">
        <i class="ri-chat-3-line text-lg"></i>
      </button>

      <button @click="activeTab = 'inspector'" :class="[
        'w-9 h-9 rounded flex items-center justify-center transition-all',
        activeTab === 'inspector'
          ? 'bg-(--accent-color) text-white shadow-sm'
          : 'text-(--text-secondary) hover:text-(--accent-color) hover:bg-(--bg-secondary)'
      ]" title="Inspector">
        <i class="ri-file-list-3-line text-lg"></i>
      </button>
    </div>

    <!-- 内容面板 -->
    <div class="flex-1 flex flex-col overflow-hidden bg-(--bg-primary)">
      <!-- AI Chat 面板 -->
      <div v-if="activeTab === 'chat'" class="flex flex-col h-full">
        <ChatPanel :messages="messages" @send-message="handleSendMessage" />
      </div>

      <!-- Inspector 面板 -->
      <div v-else-if="activeTab === 'inspector'" class="flex flex-col h-full">
        <InspectorPanel />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import InspectorPanel from './InspectorPanel.vue'
import type { Message } from '../types'

interface Props {
  messages: Message[]
}

interface Emits {
  (e: 'send-message', message: string): void
}

defineProps<Props>()
const emit = defineEmits<Emits>()

const activeTab = ref<'chat' | 'inspector'>('chat')

const handleSendMessage = (message: string) => {
  emit('send-message', message)
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- 消息列表 -->
    <ScrollPanel class="flex-1 min-h-0 px-4">
      <div ref="messagesContainerRef">
        <div v-if="messages.length === 0" class="flex flex-col items-center justify-center h-full text-center py-12">
          <div class="w-16 h-16 rounded-full bg-(--bg-secondary) flex items-center justify-center mb-4">
            <i class="ri-robot-2-line text-4xl text-(--text-secondary) opacity-50"></i>
          </div>
          <p class="text-[13px] text-(--text-secondary) leading-relaxed">
            暂无消息，请输入指令开始与 AI Agent 交互
          </p>
        </div>
        <div v-else class="py-4 space-y-4">
          <div v-for="(msg, index) in messages" :key="index" :class="[
            'flex',
            msg.role === 'user' ? 'justify-end' : 'justify-start'
          ]">
            <div :class="[
              'max-w-[85%] rounded-lg text-sm',
              msg.role === 'user'
                ? 'bg-(--accent-color) text-(--accent-text)'
                : 'bg-(--bg-secondary) text-(--text-primary) border border-(--border-color)'
            ]">
              <!-- 图片消息 -->
              <div v-if="msg.type === 'image' && msg.image" class="p-2">
                <div class="rounded-lg overflow-hidden mb-2">
                  <img :src="msg.image.url" :alt="msg.image.label" class="w-full h-auto object-contain max-h-[400px]"
                    loading="lazy" />
                </div>
                <p class="text-xs opacity-90">{{ msg.image.label }}</p>
                <p v-if="msg.image.dimensions" class="text-[10px] opacity-70 mt-1">{{ msg.image.dimensions }}</p>
              </div>
              <!-- 文本消息 -->
              <div v-else class="px-4 py-2">
                {{ msg.content }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </ScrollPanel>

    <!-- 输入区域 -->
    <div class="shrink-0 p-4 bg-(--bg-primary) border-t border-(--border-color)">
      <div class="bg-(--bg-secondary) rounded-xl border border-(--border-color) p-2">
        <textarea v-model="inputValue" placeholder="输入指令与 AI Agent 交互..."
          class="w-full bg-transparent border-none focus:ring-0 focus:outline-none text-[13px] text-(--text-primary) min-h-[80px] p-2 resize-none"
          @keydown="handleKeyDown"></textarea>

        <div class="flex items-center justify-between mt-2 px-1">
          <div class="flex items-center gap-3">
            <button class="text-(--text-secondary) hover:text-(--accent-color) transition-colors">
              <i class="ri-at-line text-lg"></i>
            </button>
            <button class="text-(--text-secondary) hover:text-(--accent-color) transition-colors">
              <i class="ri-attachment-2 text-lg"></i>
            </button>
            <button class="text-(--text-secondary) hover:text-(--accent-color) transition-colors">
              <i class="ri-emotion-happy-line text-lg"></i>
            </button>
          </div>

          <button @click="handleSubmit"
            class="bg-(--accent-color) text-(--accent-text) px-4 py-1.5 rounded-lg flex items-center gap-2 text-sm font-medium hover:opacity-90 transition-opacity">
            <i class="ri-send-plane-2-fill"></i>
            发送
          </button>
        </div>
      </div>
      <p class="text-[10px] text-(--text-secondary) text-center mt-3 opacity-60">
        AI output can be inaccurate.
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import ScrollPanel from 'primevue/scrollpanel'
import { useMessageStore } from '../stores/messageStore'

const messageStore = useMessageStore()
const { messages } = messageStore

const inputValue = ref('')
const messagesContainerRef = ref<HTMLDivElement | null>(null)

// 滚动到底部的函数
const scrollToBottom = () => {
  nextTick(() => {
    if (messagesContainerRef.value) {
      // 滚动到消息容器的底部
      messagesContainerRef.value.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  })
}

// 监听消息变化，自动滚动到底部
watch(() => messages.length, () => {
  scrollToBottom()
})

const handleSubmit = () => {
  if (inputValue.value.trim()) {
    messageStore.addMessage(inputValue.value)
    inputValue.value = ''
    // TODO: 集成实际的 AI Agent 逻辑
  }
}

const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSubmit()
  }
}
</script>

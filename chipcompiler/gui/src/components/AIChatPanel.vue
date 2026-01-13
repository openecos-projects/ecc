<template>
  <div class="h-full flex flex-col">
    <!-- 消息列表 -->
    <div ref="scrollContainerRef" class="flex-1 min-h-0 overflow-y-auto px-4 custom-scrollbar">
      <div v-if="messages.length === 0" class="flex flex-col items-center justify-center h-full text-center py-12">
        <div class="w-16 h-16 rounded-full bg-(--bg-secondary) flex items-center justify-center mb-4">
          <i class="ri-robot-2-line text-4xl text-(--text-secondary) opacity-50"></i>
        </div>
        <p class="text-[13px] text-(--text-secondary) leading-relaxed">
          暂无消息，请输入指令开始与 AI Agent 交互
        </p>
      </div>
      <div v-else class="py-4 space-y-4">
        <MessageItem v-for="msg in messages" :key="msg.id" :message="msg" @img-load="onImageLoad" />
      </div>
    </div>

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
import MessageItem from './MessageItem.vue'
import { useMessageStore } from '../stores/messageStore'

const messageStore = useMessageStore()
const { messages } = messageStore

const inputValue = ref('')
const scrollContainerRef = ref<HTMLDivElement | null>(null)

// Near-bottom 阈值（像素）
const NEAR_BOTTOM_THRESHOLD = 32

/**
 * 判断当前滚动位置是否接近底部
 */
const isNearBottom = (): boolean => {
  const el = scrollContainerRef.value
  if (!el) return true
  return el.scrollHeight - (el.scrollTop + el.clientHeight) <= NEAR_BOTTOM_THRESHOLD
}

/**
 * 直接滚动到底部（使用 scrollTop）
 */
const scrollToBottom = (smooth = true) => {
  const el = scrollContainerRef.value
  if (!el) return

  if (smooth) {
    el.scrollTo({
      top: el.scrollHeight,
      behavior: 'smooth'
    })
  } else {
    el.scrollTop = el.scrollHeight
  }
}

/**
 * 智能滚动到底部
 * @param force 是否强制滚动（忽略 near-bottom 判定）
 */
const scrollToBottomIfNeeded = (force = false) => {
  nextTick(() => {
    if (force || isNearBottom()) {
      scrollToBottom()
    }
  })
}

/**
 * 图片加载完成回调
 * 图片加载后高度变化，需要重新滚动到底部
 */
const onImageLoad = () => {
  // 使用 requestAnimationFrame 确保在渲染完成后滚动
  requestAnimationFrame(() => {
    if (isNearBottom()) {
      scrollToBottom()
    }
  })
}

// 监听消息变化，自动滚动到底部
watch(() => messages.length, () => {
  // 新消息到来时强制滚动到底部
  scrollToBottomIfNeeded(true)
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

<style scoped>
.custom-scrollbar {
  scrollbar-width: thin;
  scrollbar-color: var(--border-color) transparent;
}

.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
}

.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}

.custom-scrollbar::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 3px;
}

.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: var(--text-secondary);
}
</style>

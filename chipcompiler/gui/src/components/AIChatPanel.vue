<template>
  <div class="h-full flex flex-col min-w-0">
    <!-- 消息列表 -->
    <div ref="scrollContainerRef"
      class="flex-1 min-h-0 min-w-0 overflow-y-auto overflow-x-hidden px-4 custom-scrollbar">
      <div v-if="messages.length === 0" class="flex flex-col items-center justify-center h-full text-center py-12">
        <div class="w-16 h-16 rounded-full bg-(--bg-secondary) flex items-center justify-center mb-4">
          <i class="ri-robot-2-line text-4xl text-(--text-secondary) opacity-50"></i>
        </div>
        <p class="text-[13px] text-(--text-secondary) leading-relaxed">
          暂无消息，请输入指令开始与 Chat 交互
        </p>
      </div>
      <div v-else class="messages-container py-4 space-y-4 min-w-0 w-full max-w-full overflow-hidden">
        <MessageItem v-for="msg in messages" :key="msg.id" :message="msg" @img-load="onImageLoad"
          class="message-item w-full min-w-0 max-w-full" />
      </div>
    </div>

    <!-- 输入区域 -->
    <div class="shrink-0 p-4 bg-(--bg-primary) border-t border-(--border-color)">
      <div class="bg-(--bg-secondary) rounded-xl border border-(--border-color) p-2">
        <textarea v-model="inputValue" placeholder=""
          class="w-full bg-transparent border-none focus:ring-0 focus:outline-none text-[13px] text-(--text-primary) min-h-[80px] p-2 resize-none"
          @keydown="handleKeyDown"></textarea>

        <div class="flex items-center justify-between mt-2 px-1">
          <div class="flex items-center gap-3">
            <!-- 模式选择器 - Cursor 风格 -->
            <div class="relative" ref="modeSelectRef">
              <button @click="toggleModeMenu"
                class="mode-selector flex items-center gap-1.5 px-2 py-0.5 rounded-full border border-(--border-color) bg-(--bg-primary) hover:border-(--text-secondary)/50 transition-all">
                <i :class="[currentMode.icon, 'text-sm text-(--text-secondary)']"></i>
                <i class="ri-arrow-down-s-line text-xs text-(--text-secondary) transition-transform duration-200"
                  :class="{ 'rotate-180': showModeMenu }"></i>
              </button>

              <!-- 上拉菜单 -->
              <Transition name="popup">
                <div v-if="showModeMenu"
                  class="absolute bottom-full left-0 mb-2 min-w-[140px] bg-(--bg-tertiary) border border-(--border-color)/50 rounded-xl shadow-xl overflow-hidden z-50 backdrop-blur-sm">
                  <div class="py-1">
                    <div v-for="mode in modes" :key="mode.id" @click="selectMode(mode.id)" :class="[
                      'flex items-center gap-2.5 px-3 py-2 cursor-pointer transition-all',
                      currentModeId === mode.id
                        ? 'text-(--text-primary) bg-(--bg-secondary)'
                        : 'text-(--text-secondary) hover:text-(--text-primary) hover:bg-(--bg-secondary)/50'
                    ]">
                      <i :class="[mode.icon, 'text-sm']"></i>
                      <span class="text-xs font-medium flex-1">{{ mode.label }}</span>
                      <i v-if="currentModeId === mode.id" class="ri-check-line text-xs text-(--accent-color)"></i>
                    </div>
                  </div>
                </div>
              </Transition>
            </div>
          </div>

          <button @click="handleSubmit"
            class="bg-(--accent-color) text-(--accent-text) px-4 py-1.5 rounded-lg flex items-center gap-2 text-sm font-medium hover:opacity-90 transition-opacity">
            <i class="ri-send-plane-2-fill"></i>
            发送
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import MessageItem from './MessageItem.vue'
import { useMessageStore } from '../stores/messageStore'

const messageStore = useMessageStore()
const { messages } = messageStore

const inputValue = ref('')
const scrollContainerRef = ref<HTMLDivElement | null>(null)

// 模式选择器相关
const modeSelectRef = ref<HTMLDivElement | null>(null)
const showModeMenu = ref(false)
const currentModeId = ref<'chat' | 'builder'>('chat')

// 模式定义
const modes = [
  { id: 'chat' as const, label: 'Chat', icon: 'ri-chat-3-line' },
  { id: 'builder' as const, label: 'Builder', icon: 'ri-infinity-line' },
]

// 当前选中的模式
const currentMode = computed(() => {
  return modes.find(m => m.id === currentModeId.value) || modes[0]
})

// 切换菜单显示
const toggleModeMenu = () => {
  showModeMenu.value = !showModeMenu.value
}

// 选择模式
const selectMode = (modeId: 'chat' | 'builder') => {
  currentModeId.value = modeId
  showModeMenu.value = false
}

// 点击外部关闭菜单
const handleClickOutside = (e: MouseEvent) => {
  if (modeSelectRef.value && !modeSelectRef.value.contains(e.target as Node)) {
    showModeMenu.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})

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

/* 消息容器约束 - 防止内容撑开父容器 */
.messages-container {
  contain: layout style;
  box-sizing: border-box;
}

.message-item {
  contain: layout style paint;
  box-sizing: border-box;
}

/* 上拉菜单动画 */
.popup-enter-active,
.popup-leave-active {
  transition: all 0.15s ease-out;
}

.popup-enter-from,
.popup-leave-to {
  opacity: 0;
  transform: translateY(4px);
}
</style>

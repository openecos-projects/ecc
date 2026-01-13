<template>
  <div :class="[
    'flex w-full',
    message.role === 'user' ? 'justify-end' : 'justify-start'
  ]">
    <div :class="[
      'max-w-[85%] rounded-lg text-sm',
      message.role === 'user'
        ? 'bg-(--accent-color) text-(--accent-text)'
        : 'bg-(--bg-secondary) text-(--text-primary) border border-(--border-color)'
    ]">
      <!-- 图片消息 -->
      <div v-if="message.type === 'image' && message.image" class="p-2">
        <div class="rounded-lg overflow-hidden mb-2">
          <img :src="message.image.url" :alt="message.image.label" class="w-full h-auto object-contain max-h-[400px]"
            loading="lazy" @load="handleImageLoad" />
        </div>
        <p class="text-xs opacity-90">{{ message.image.label }}</p>
        <p v-if="message.image.dimensions" class="text-[10px] opacity-70 mt-1">{{ message.image.dimensions }}</p>
      </div>

      <!-- 文本消息 -->
      <div v-else class="px-4 py-2">
        <!-- 加载状态 -->
        <div v-if="message.status === 'loading' && !message.content" class="flex items-center gap-2">
          <div class="loading-dots flex gap-1">
            <span class="w-2 h-2 bg-current rounded-full animate-bounce" style="animation-delay: 0ms;"></span>
            <span class="w-2 h-2 bg-current rounded-full animate-bounce" style="animation-delay: 150ms;"></span>
            <span class="w-2 h-2 bg-current rounded-full animate-bounce" style="animation-delay: 300ms;"></span>
          </div>
          <span class="text-xs opacity-70">正在思考...</span>
        </div>

        <!-- 错误状态 -->
        <div v-else-if="message.status === 'error'" class="flex items-center gap-2 text-red-500">
          <i class="ri-error-warning-line"></i>
          <span>{{ message.content || '消息发送失败' }}</span>
        </div>

        <!-- 正常内容（Markdown 渲染） -->
        <div v-else class="markdown-body" v-html="renderedContent"></div>

        <!-- 流式加载时显示光标 -->
        <span v-if="message.status === 'loading' && message.content"
          class="inline-block w-2 h-4 bg-current animate-pulse ml-0.5"></span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import type { Message } from '../types'

const props = defineProps<{
  message: Message
}>()

const emit = defineEmits<{
  (e: 'img-load'): void
}>()

const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true
})

const renderedContent = computed(() => {
  return md.render(props.message.content)
})

const handleImageLoad = () => {
  emit('img-load')
}
</script>

<style scoped>
.markdown-body {
  line-height: 1.6;
  word-break: break-word;
}

.markdown-body :deep(p) {
  margin-bottom: 0.5rem;
}

.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(code) {
  background-color: rgba(0, 0, 0, 0.1);
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
  font-family: monospace;
}

.markdown-body :deep(pre) {
  background-color: var(--bg-secondary);
  padding: 1rem;
  border-radius: 8px;
  overflow-x: auto;
  margin: 0.5rem 0;
  border: 1px solid var(--border-color);
}

.markdown-body :deep(pre code) {
  background-color: transparent;
  padding: 0;
  display: block;
}

.markdown-body :deep(ul) {
  list-style-type: disc;
  padding-left: 1.5rem;
  margin-bottom: 0.5rem;
}

.markdown-body :deep(ol) {
  list-style-type: decimal;
  padding-left: 1.5rem;
  margin-bottom: 0.5rem;
}

.markdown-body :deep(li) {
  margin-bottom: 0.25rem;
}

.markdown-body :deep(a) {
  color: var(--accent-color);
  text-decoration: underline;
}

.markdown-body :deep(h1) {
  font-size: 1.5rem;
  font-weight: 700;
}

.markdown-body :deep(h2) {
  font-size: 1.25rem;
  font-weight: 600;
}

.markdown-body :deep(h3) {
  font-size: 1.1rem;
  font-weight: 600;
}

.markdown-body :deep(strong) {
  font-weight: 600;
}

.markdown-body :deep(em) {
  font-style: italic;
}

.markdown-body :deep(u) {
  text-decoration: underline;
}

.markdown-body :deep(blockquote) {
  border-left: 4px solid var(--accent-color);
  padding-left: 1rem;
  color: var(--text-secondary);
  font-style: italic;
  margin: 1rem 0;
  background-color: var(--bg-secondary);
  padding-top: 0.5rem;
  padding-bottom: 0.5rem;
  border-radius: 0 4px 4px 0;
}

/* 加载动画 */
.loading-dots span {
  animation: bounce 1s infinite;
}

@keyframes bounce {

  0%,
  80%,
  100% {
    transform: translateY(0);
  }

  40% {
    transform: translateY(-6px);
  }
}
</style>

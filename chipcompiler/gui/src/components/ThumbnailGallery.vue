<template>
  <!-- 列表视图 -->
  <div class="flex flex-col h-full bg-(--bg-primary)">
    <!-- 标题 -->
    <div class="flex items-center justify-between px-4 py-1 border-b border-(--border-color)">
      <div class="flex items-center gap-2">
        <i class="ri-stack-line text-(--text-secondary)"></i>
        <h3 class="text-sm font-semibold text-(--text-primary)">Information</h3>
      </div>
      <div class="flex items-center gap-2">
        <button class="p-1 text-(--text-secondary) hover:text-(--text-primary) transition-colors">
          <i class="ri-filter-3-line text-sm"></i>
        </button>
        <button class="p-1 text-(--text-secondary) hover:text-(--text-primary) transition-colors">
          <i class="ri-more-2-line text-sm"></i>
        </button>
      </div>
    </div>

    <!-- 缩略图网格 -->
    <ScrollPanel class="flex-1">
      <div class="flex flex-row gap-4 p-4 overflow-x-auto">
        <div v-for="thumb in thumbnails.slice(0, 4)" :key="thumb.id" class="shrink-0 w-48 group cursor-pointer"
          @click="handleImageClick(thumb)">
          <div
            class="aspect-video bg-(--bg-secondary) rounded-lg border border-(--border-color) flex items-center justify-center overflow-hidden group-hover:border-(--accent-color) transition-all shadow-sm will-change-transform">
            <img v-if="thumb.thumbnailUrl && !imageError.has(thumb.id)" 
              :src="thumb.thumbnailUrl" 
              :alt="thumb.label"
              class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300 will-change-transform"
              loading="lazy"
              decoding="async"
              @error="handleImageError(thumb.id)" />
            <div v-else class="flex flex-col items-center gap-2">
              <i class="ri-image-line text-3xl text-(--text-secondary)"></i>
              <span class="text-[10px] text-(--text-secondary)">Image Loading...</span>
            </div>
          </div>
          <div class="mt-2 text-center">
            <p class="text-xs font-medium text-(--text-primary)">
              {{ thumb.label }}
            </p>
          </div>
        </div>
      </div>
    </ScrollPanel>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import ScrollPanel from 'primevue/scrollpanel'
import type { Thumbnail } from '../types'
import { useMessageStore } from '../stores/messageStore'

const messageStore = useMessageStore()
const selectedImage = ref<Thumbnail | null>(null)
const imageError = ref<Set<number>>(new Set())
const zoom = ref(100)

// 示例数据 - 你可以替换为真实的图片路径
const thumbnails: Thumbnail[] = [
  {
    id: 1,
    label: '版图 - 第一层',
    description: '金属互连层 M1',
    thumbnailUrl: '/images/thumbnails/layout1.png',
    imageUrl: '/images/thumbnails/layout1.png',
    size: '2.4 MB',
    dimensions: '1920 × 1080',
    format: 'PNG'
  },
  {
    id: 2,
    label: '版图 - 第二层',
    description: '金属互连层 M2',
    thumbnailUrl: '/images/thumbnails/layout2.png',
    imageUrl: '/images/thumbnails/layout2.png',
    size: '2.1 MB',
    dimensions: '1920 × 1080',
    format: 'PNG'
  },
  {
    id: 3,
    label: '版图 - 第三层',
    description: '金属互连层 M3',
    thumbnailUrl: '/images/thumbnails/layout3.png',
    imageUrl: '/images/thumbnails/layout3.png',
    size: '2.8 MB',
    dimensions: '2048 × 1152',
    format: 'PNG'
  },
  {
    id: 4,
    label: '版图 - 第四层',
    description: '金属互连层 M4',
    thumbnailUrl: '/images/thumbnails/layout4.png',
    imageUrl: '/images/thumbnails/layout4.png',
    size: '3.2 MB',
    dimensions: '2048 × 1152',
    format: 'PNG'
  },
  {
    id: 5,
    label: '版图 - 第五层',
    description: '通孔层 VIA',
    thumbnailUrl: '/images/thumbnails/layout5.png',
    imageUrl: '/images/thumbnails/layout5.png',
    size: '1.9 MB',
    dimensions: '1920 × 1080',
    format: 'PNG'
  },
  {
    id: 6,
    label: '版图 - 第六层',
    description: '顶层金属 MT',
    thumbnailUrl: '/images/thumbnails/layout6.png',
    imageUrl: '/images/thumbnails/layout6.png',
    size: '2.6 MB',
    dimensions: '1920 × 1080',
    format: 'PNG'
  },
]

const handleImageClick = (thumb: Thumbnail) => {
  selectedImage.value = thumb
  zoom.value = 100 // 重置缩放
  // 将图片添加到消息流中
  messageStore.addImageMessage(thumb)
}

const handleImageError = (id: number) => {
  imageError.value = new Set(imageError.value).add(id)
}

</script>

import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Message, Thumbnail } from '../types'

export const useMessageStore = defineStore('messages', () => {
  const messages = ref<Message[]>([])
  
  const addMessage = (content: string, role: string = 'user') => {
    messages.value.push({ 
      role, 
      content, 
      type: 'text' 
    })
  }
  
  const addImageMessage = (thumbnail: Thumbnail) => {
    messages.value.push({
      role: 'user',
      content: `查看图片: ${thumbnail.label}`,
      type: 'image',
      image: {
        url: thumbnail.imageUrl || thumbnail.thumbnailUrl || '',
        label: thumbnail.label,
        dimensions: thumbnail.dimensions,
        thumbnailId: thumbnail.id
      }
    })
  }
  
  const clearMessages = () => {
    messages.value = []
  }
  
  return { 
    messages, 
    addMessage, 
    addImageMessage, 
    clearMessages 
  }
})


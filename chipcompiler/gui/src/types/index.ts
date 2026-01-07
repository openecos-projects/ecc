export interface Message {
  role: string
  content: string
  type?: 'text' | 'image'
  image?: {
    url: string
    label?: string
    dimensions?: string
    thumbnailId?: number
  }
}

export interface Thumbnail {
  id: number
  label: string
  description?: string
  thumbnailUrl?: string
  imageUrl?: string
  size?: string
  dimensions?: string
  format?: string
}

export interface Project {
  id: string
  name: string
  path: string
  lastOpened: Date
}

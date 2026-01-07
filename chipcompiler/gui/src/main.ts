import { createApp } from 'vue'
import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import Aura from '@primevue/themes/aura'
import router from './router'
import App from './App.vue'
import './styles/index.css'
import 'remixicon/fonts/remixicon.css'

const app = createApp(App)
const pinia = createPinia()

app.use(PrimeVue, {
  theme: {
    preset: Aura,
    options: {
      darkModeSelector: '.dark',
      cssLayer: {
        name: 'primevue',
        order: 'tailwind-base, primevue, tailwind-utilities'
      }
    }
  }
})

app.use(pinia)
app.use(router)

// 挂载应用
app.mount('#app')

// 在 Tauri 环境中，通知后端应用已准备就绪
if ('__TAURI_IPC__' in window) {
  // 打印调试信息
  console.log('=== Frontend Debug Info ===')
  console.log('window.innerWidth:', window.innerWidth)
  console.log('window.innerHeight:', window.innerHeight)
  console.log('window.devicePixelRatio:', window.devicePixelRatio)
  console.log('document.body.clientWidth:', document.body.clientWidth)
  console.log('document.body.clientHeight:', document.body.clientHeight)
  
  // 等待路由和渲染完成
  router.isReady().then(() => {
    // 再等待一帧确保渲染完成
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        console.log('Application ready')
        console.log('After render - window.innerWidth:', window.innerWidth)
        console.log('After render - window.innerHeight:', window.innerHeight)
      })
    })
  })
}


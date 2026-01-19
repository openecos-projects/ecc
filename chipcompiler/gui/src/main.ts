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
      darkModeSelector: '.dark'
    }
  }
})

app.use(pinia)
app.use(router)

// 挂载应用
app.mount('#app')

// 在 Tauri 环境中，通知后端应用已准备就绪
const isTauri = !!(window as any).__TAURI_IPC__ || !!(window as any).__TAURI_METADATA__;

if (isTauri) {
  // 异步触发窗口显示，不阻塞主流程
  (async () => {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await router.isReady();
      // 等待 DOM 渲染
      requestAnimationFrame(() => {
        invoke('show_main_window').catch(console.error);
        console.log('ECC Window show signal sent');
      });
    } catch (e) {
      console.error('Failed to signal window show:', e);
    }
  })();
}


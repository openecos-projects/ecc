import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { resolve } from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  },
  plugins: [
    vue({
      template: {
        compilerOptions: {
          // 优化编译性能
          hoistStatic: true,
          cacheHandlers: true
        }
      }
    }),
    tailwindcss()
  ],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    watch: {
      ignored: ['**/src-tauri/**']
    }
  },
  build: {
    // Tauri 环境优化
    target: 'esnext',
    minify: 'esbuild',
    // 减少代码分割来提升加载速度
    rollupOptions: {
      output: {
        manualChunks: {
          'vue-vendor': ['vue', 'vue-router'],
          'primevue-vendor': ['primevue']
        }
      }
    },
    // 减少 chunk 大小警告阈值
    chunkSizeWarningLimit: 1000,
    // 优化资源内联
    assetsInlineLimit: 4096
  },
  optimizeDeps: {
    include: ['vue', 'vue-router', 'primevue']
  }
})


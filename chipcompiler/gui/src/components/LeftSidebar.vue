<template>
  <div class="flex h-full">
    <!-- 第一栏：流程步骤导航 (优化版) -->
    <div
      class="w-[52px] shrink-0 bg-(--bg-sidebar) border-r border-(--border-color) flex flex-col justify-between py-3">
      <div>
        <router-link v-for="stage in flowStages" :key="stage.path"
          :to="stage.available !== false ? '/workspace/' + stage.path : route.path"
          @click="stage.available === false && $event.preventDefault()"
          class="flex flex-col items-center justify-center py-4 transition-all group relative mb-1" :class="[
            currentStage === stage.path ? 'text-(--accent-color)' : 'text-(--text-secondary)',
            stage.available === false ? 'opacity-40 grayscale cursor-not-allowed' : 'hover:bg-white/5'
          ]">
          <!-- 选中状态的指示条 -->
          <div v-if="currentStage === stage.path"
            class="absolute left-0 top-2 bottom-2 w-1 bg-(--accent-color) rounded-r-full shadow-[0_0_10px_var(--accent-color)]">
          </div>

          <!-- 图标容器 -->
          <div class="relative transition-transform group-hover:-translate-y-0.5">
            <i :class="stage.icon" class="text-xl mb-1.5 inline-block"></i>

            <!-- 完成状态指示点 -->
            <i v-if="stage.completed"
              class="ri-checkbox-circle-fill absolute -top-1 -right-1 text-[10px] text-green-500 bg-(--bg-sidebar) rounded-full"></i>
          </div>

          <span class="text-[9px] font-bold text-center leading-tight uppercase tracking-tighter scale-90">
            {{ stage.label }}
          </span>
        </router-link>
      </div>
      <button @click="toggleTheme" class="p-2 text-(--text-secondary) hover:text-(--text-primary) transition-colors"
        title="切换主题">
        <i :class="isDark ? 'ri-sun-line' : 'ri-moon-line'" class="text-lg"></i>
      </button>
    </div>

    <!-- 第二栏：流程进度面板 (Configure 页面不显示) -->
    <div v-if="showProgressPanel"
      class="w-[240px] min-w-[200px] max-w-[300px] bg-(--bg-primary) border-r border-(--border-color) flex flex-col overflow-hidden shrink-0">
      <!-- 顶部标题栏 -->
      <div class="px-4 py-3 border-b border-(--border-color)">
        <div class="flex items-center gap-2">
          <div class="w-8 h-8 rounded-lg bg-(--accent-color)/20 flex items-center justify-center">
            <i class="ri-focus-2-line text-(--accent-color) text-lg"></i>
          </div>
          <div>
            <h3 class="text-[13px] font-bold text-(--text-primary)">Run Placement</h3>
            <p class="text-[10px] text-(--text-secondary)">iEDA Place Engine</p>
          </div>
        </div>
      </div>

      <!-- 进度统计 -->
      <div class="px-4 py-3 border-b border-(--border-color) bg-(--bg-secondary)/30">
        <div class="flex items-center justify-between mb-2">
          <span class="text-[10px] text-(--text-secondary) uppercase tracking-wider">Progress</span>
          <span class="text-[11px] font-bold text-(--accent-color)">{{ completedSteps }}/{{ placementSteps.length
          }}</span>
        </div>
        <div class="h-1.5 bg-(--bg-secondary) rounded-full overflow-hidden">
          <div class="h-full bg-(--accent-color) rounded-full transition-all duration-500"
            :style="{ width: `${(completedSteps / placementSteps.length) * 100}%` }"></div>
        </div>
        <div class="flex items-center justify-between mt-2 text-[9px] text-(--text-secondary)">
          <span>Total: {{ totalTime }}</span>
          <span
            :class="overallStatus === 'completed' ? 'text-green-500' : overallStatus === 'running' ? 'text-blue-400' : 'text-(--text-secondary)'">
            {{ overallStatus === 'completed' ? 'Completed' : overallStatus === 'running' ? 'Running...' : 'Ready' }}
          </span>
        </div>
      </div>

      <!-- 步骤列表 -->
      <div class="flex-1 overflow-y-auto">
        <div class="p-3 space-y-1">
          <div v-for="(step, index) in placementSteps" :key="step.id" class="group relative"
            :class="{ 'opacity-50': step.status === 'pending' && index > 0 && placementSteps[index - 1].status === 'pending' }">
            <!-- 连接线：从圆形底部到下一个圆形顶部 -->
            <div v-if="index < placementSteps.length - 1"
              class="absolute left-[16px] top-[42px] w-0.5 h-[calc(100%-34px)]" :class="[
                step.status === 'completed' ? 'bg-green-500/50' :
                  step.status === 'running' ? 'bg-linear-to-b from-blue-400/50 to-(--border-color)' :
                    'bg-(--border-color)'
              ]"></div>

            <!-- 步骤项 -->
            <div
              class="flex items-start gap-3 p-2 rounded-lg transition-all hover:bg-(--bg-secondary)/50 cursor-pointer"
              :class="{ 'bg-(--bg-secondary)/30': step.status === 'running' }">
              <!-- 状态图标 -->
              <div class="relative shrink-0 mt-0.5">
                <!-- 完成状态 -->
                <div v-if="step.status === 'completed'"
                  class="w-[30px] h-[30px] rounded-full bg-green-500/20 border-2 border-green-500 flex items-center justify-center">
                  <i class="ri-check-line text-green-500 text-sm"></i>
                </div>
                <!-- 运行状态 -->
                <div v-else-if="step.status === 'running'"
                  class="w-[30px] h-[30px] rounded-full bg-blue-500/20 border-2 border-blue-400 flex items-center justify-center">
                  <i class="ri-loader-4-line text-blue-400 text-sm animate-spin"></i>
                </div>
                <!-- 失败状态 -->
                <div v-else-if="step.status === 'failed'"
                  class="w-[30px] h-[30px] rounded-full bg-red-500/20 border-2 border-red-500 flex items-center justify-center">
                  <i class="ri-close-line text-red-500 text-sm"></i>
                </div>
                <!-- 等待状态 -->
                <div v-else
                  class="w-[30px] h-[30px] rounded-full bg-(--bg-secondary) border-2 border-(--border-color) flex items-center justify-center">
                  <span class="text-[10px] font-bold text-(--text-secondary)">{{ index + 1 }}</span>
                </div>
              </div>

              <!-- 步骤信息 -->
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2">
                  <span class="text-[12px] font-semibold truncate" :class="[
                    step.status === 'completed' ? 'text-green-500' :
                      step.status === 'running' ? 'text-blue-400' :
                        step.status === 'failed' ? 'text-red-500' :
                          'text-(--text-primary)'
                  ]">
                    {{ step.name }}
                  </span>
                  <!-- 运行中的脉冲动画 -->
                  <span v-if="step.status === 'running'"
                    class="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse"></span>
                </div>
                <p class="text-[10px] text-(--text-secondary) mt-0.5 truncate">{{ step.description }}</p>
                <!-- 耗时显示 -->
                <div v-if="step.duration || step.status === 'running'" class="flex items-center gap-2 mt-1">
                  <i class="ri-time-line text-[10px] text-(--text-secondary)"></i>
                  <span class="text-[10px]"
                    :class="step.status === 'running' ? 'text-blue-400' : 'text-(--text-secondary)'">
                    {{ step.duration || 'calculating...' }}
                  </span>
                </div>
              </div>

              <!-- 展开箭头 -->
              <i
                class="ri-arrow-right-s-line text-(--text-secondary) opacity-0 group-hover:opacity-100 transition-opacity shrink-0"></i>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部操作栏 -->
      <div class="p-3 border-t border-(--border-color) bg-(--bg-secondary)/30 space-y-2">
        <!-- 操作按钮组 -->
        <div class="flex gap-2">
          <button @click="handleRunFlow" :disabled="isLoading"
            class="flex-1 flex items-center justify-center gap-2 px-3 py-2 bg-(--accent-color) text-white text-[11px] font-bold rounded hover:brightness-110 active:scale-[0.98] transition-all disabled:opacity-50 shadow-lg shadow-(--accent-color)/20">
            <i :class="isLoading ? 'ri-loader-4-line animate-spin' : 'ri-play-fill'"></i>
            {{ isLoading ? 'RUNNING' : 'RUN Flow' }}
          </button>
          <button
            class="px-3 py-2 bg-(--bg-secondary) text-(--text-secondary) text-[11px] font-bold rounded border border-(--border-color) hover:text-(--text-primary) hover:border-(--accent-color) transition-all"
            title="Stop">
            <i class="ri-stop-fill"></i>
          </button>
          <button
            class="px-3 py-2 bg-(--bg-secondary) text-(--text-secondary) text-[11px] font-bold rounded border border-(--border-color) hover:text-(--text-primary) hover:border-(--accent-color) transition-all"
            title="Reset">
            <i class="ri-refresh-line"></i>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useTauri } from '@/composables/useTauri'
import { useThemeStore } from '@/stores/themeStore'
const { isInTauri, ensureTauri } = useTauri()
const themeStore = useThemeStore()
const route = useRoute()
const isDark = computed(() => themeStore.themeName === 'dark')
const isLoading = ref(false)

// Placement 流程步骤定义
interface PlacementStep {
  id: string
  name: string
  description: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  duration?: string
}

const placementSteps = ref<PlacementStep[]>([
  {
    id: 'init',
    name: 'Initialize',
    description: 'Load design and setup environment',
    status: 'completed',
    duration: '2.3s'
  },
  {
    id: 'global',
    name: 'Global Placement',
    description: 'Coarse cell spreading optimization',
    status: 'completed',
    duration: '45.8s'
  },
  {
    id: 'optimize',
    name: 'Place Optimization',
    description: 'Timing-driven placement refinement',
    status: 'completed',
    duration: '23.1s'
  },
  {
    id: 'detail',
    name: 'Detail Placement',
    description: 'Fine-grained cell positioning',
    status: 'completed',
    duration: '10.2s'
  },
  {
    id: 'legal',
    name: 'Legalization',
    description: 'Remove overlaps and align to rows',
    status: 'completed',
    duration: '5.6s'
  },
  {
    id: 'save',
    name: 'Save Data',
    description: 'Export DEF, features and reports',
    status: 'completed',
    duration: '2.3s'
  }
])

// 计算属性
const completedSteps = computed(() => {
  return placementSteps.value.filter(s => s.status === 'completed').length
})
const toggleTheme = () => {
  themeStore.toggleTheme()
}
const totalTime = computed(() => {
  const times = placementSteps.value
    .filter(s => s.duration)
    .map(s => parseFloat(s.duration!.replace('s', '')))
  const total = times.reduce((a, b) => a + b, 0)
  return total > 0 ? `${total.toFixed(1)}s` : '--'
})

const overallStatus = computed(() => {
  if (placementSteps.value.some(s => s.status === 'running')) return 'running'
  if (placementSteps.value.every(s => s.status === 'completed')) return 'completed'
  if (placementSteps.value.some(s => s.status === 'failed')) return 'failed'
  return 'pending'
})


// 流程步骤配置
const flowStages = [
  { label: 'Home', path: 'home', icon: 'ri-home-4-line', group: 'setup', completed: false, available: true },
  { label: 'Config', path: 'configure', icon: 'ri-settings-3-line', group: 'setup', completed: false, available: true },
  { label: 'Synth', path: 'synthesis', icon: 'ri-node-tree', group: 'run', completed: true, available: true },
  { label: 'Floor', path: 'floorplan', icon: 'ri-layout-4-line', group: 'run', completed: true, available: true },
  { label: 'Place', path: 'place', icon: 'ri-focus-2-line', group: 'run', completed: true, available: true },
  { label: 'CTS', path: 'cts', icon: 'ri-git-merge-line', group: 'run', completed: false, available: false },
  { label: 'Route', path: 'route', icon: 'ri-route-line', group: 'run', completed: false, available: false },
  { label: 'Signoff', path: 'signoff', icon: 'ri-checkbox-circle-line', group: 'run', completed: false, available: false }
]

const currentStage = computed(() => {
  const pathParts = route.path.split('/')
  return pathParts[pathParts.length - 1] || 'home'
})

// 是否显示进度面板 (Configure 页面不显示)
const showProgressPanel = computed(() => {
  return currentStage.value !== 'configure' && currentStage.value !== 'home'
})

const handleRunFlow = async () => {
  // 检查是否在 Tauri 环境中
  if (!isInTauri) {
    console.warn('当前不在 Tauri 环境中，无法执行 Python 脚本');
    ensureTauri(true) // 显示警告弹窗
    return;
  }

  if (isLoading.value) return

  isLoading.value = true

  // 获取当前路由名称
  const routeName = route.name || route.path || 'unknown'

  try {
    console.log('handleRunFlow', routeName)
  } catch (error) {
    console.error('❌ 调用 Python 失败:', error)
  } finally {
    isLoading.value = false
  }
}
</script>

<style scoped>
/* 自定义滚动条 */
::-webkit-scrollbar {
  width: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--text-secondary);
}
</style>

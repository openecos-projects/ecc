<template>
  <div class="flex h-full">
    <!-- 第一栏：流程步骤导航 (优化版) -->
    <div class="w-[52px] shrink-0 bg-(--bg-sidebar) border-r border-(--border-color) flex flex-col py-3">
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

    <!-- 第二栏：Navigator 面板 -->
    <div
      class="w-[240px] min-w-[200px] max-w-[300px] bg-(--bg-primary) border-r border-(--border-color) flex flex-col overflow-hidden shrink-0">
      <!-- 顶部标签栏 -->
      <div v-if="hasData" class="h-10 flex items-center border-b border-(--border-color) px-3 gap-1">
        <button v-for="tab in tabs" :key="tab.id" @click="activeTab = tab.id as 'hierarchy' | 'files' | 'search'"
          class="px-3 py-1.5 text-[11px] font-bold uppercase tracking-wide transition-all rounded" :class="[
            activeTab === tab.id
              ? 'text-(--accent-color) bg-(--accent-color)/20 border-(--accent-color)/50' : 'text-(--text-secondary) border-transparent hover:bg-(--bg-hover)',
            'h-8 px-2 flex items-center gap-1.5 rounded border transition-all'
          ]">
          {{ tab.label }}
        </button>

        <div class="ml-auto">
          <button class="p-1 text-(--text-secondary) hover:text-(--text-primary) transition-colors">
            <i class="ri-more-2-fill"></i>
          </button>
        </div>
      </div>

      <!-- Navigator 内容区 -->
      <div class="flex-1 overflow-hidden">
        <!-- 引导模式：只有在没有数据时显示 -->
        <div v-if="!hasData" class="h-full flex flex-col p-5 bg-linear-to-b from-(--bg-primary) to-(--bg-secondary)/20">
          <div class="mb-8">
            <div class="flex items-center gap-2 mb-2">
              <span class="w-2 h-2 rounded-full bg-amber-500 animate-pulse"></span>
              <span class="text-[10px] font-bold text-amber-500 uppercase tracking-widest">Setup Required</span>
            </div>
            <h2 class="text-lg font-bold text-(--text-primary) leading-tight">Flow Roadmap</h2>
            <p class="text-[11px] text-(--text-secondary) mt-1">Execute the design flow to initialize your project.</p>
          </div>

          <!-- 步骤路线图 -->
          <div class="space-y-0 relative flex-1">
            <div class="absolute left-[11px] top-2 bottom-8 w-px border-l border-dashed border-(--border-color)"></div>

            <div class="relative pl-8 pb-8 group">
              <div
                class="absolute left-0 top-0.5 w-6 h-6 rounded-full bg-(--bg-secondary) border border-(--border-color) flex items-center justify-center group-hover:border-(--accent-color) transition-colors">
                <i class="ri-file-settings-line text-[12px] text-(--text-secondary)"></i>
              </div>
              <h4 class="text-[12px] font-bold text-(--text-primary)">Parse Design</h4>
              <p class="text-[10px] text-(--text-secondary) mt-0.5 leading-relaxed">Verilog parsing and SDC constraints
                validation.</p>
            </div>

            <div class="relative pl-8 pb-8 group opacity-60">
              <div
                class="absolute left-0 top-0.5 w-6 h-6 rounded-full bg-(--bg-secondary) border border-(--border-color) flex items-center justify-center group-hover:border-(--accent-color) transition-colors">
                <i class="ri-node-tree text-[12px] text-(--text-secondary)"></i>
              </div>
              <h4 class="text-[12px] font-bold text-(--text-primary)">Extract Hierarchy</h4>
              <p class="text-[10px] text-(--text-secondary) mt-0.5 leading-relaxed">Generate netlist and build module
                hierarchy tree.</p>
            </div>

            <div class="relative pl-8 group opacity-40">
              <div
                class="absolute left-0 top-0.5 w-6 h-6 rounded-full bg-(--bg-secondary) border border-(--border-color) flex items-center justify-center">
                <i class="ri-layout-masonry-line text-[12px] text-(--text-secondary)"></i>
              </div>
              <h4 class="text-[12px] font-bold text-(--text-primary)">Floorplan View</h4>
              <p class="text-[10px] text-(--text-secondary) mt-0.5 leading-relaxed">Enable physical visualization and
                power routing.</p>
            </div>
          </div>

          <div class="mt-auto pt-4 border-t border-(--border-color)/50">
            <div class="p-3 rounded-lg bg-(--accent-color)/5 border border-(--accent-color)/10">
              <p class="text-[11px] text-(--text-secondary) leading-relaxed">
                <i class="ri-lightbulb-line text-(--accent-color) mr-1"></i>
                The <span class="text-(--text-primary) font-semibold">Run Flow</span> button below will start the
                pipeline from current stage.
              </p>
            </div>
          </div>
        </div>

        <!-- 常规模式：数据加载后显示内容 -->
        <template v-else>
          <!-- Hierarchy Tab -->
          <div v-if="activeTab === 'hierarchy'" class="h-full flex flex-col">
            <!-- 搜索框 -->
            <div class="px-3 py-2 border-b border-(--border-color)">
              <div class="relative">
                <i
                  class="ri-search-line absolute left-2.5 top-1/2 -translate-y-1/2 text-[13px] text-(--text-secondary)"></i>
                <input type="text" placeholder="Search Nets..."
                  class="w-full pl-8 pr-3 py-1.5 text-[11px] bg-(--bg-secondary) border border-(--border-color) rounded text-(--text-primary) placeholder-text-(--text-secondary) focus:outline-none focus:border-(--accent-color) transition-all" />
              </div>
            </div>

            <!-- 层级树 (仅保留结构示意，实际建议动态生成) -->
            <div class="flex-1 overflow-y-auto p-2">
              <div class="space-y-0.5">
                <div class="group">
                  <button @click="toggleNode('top')"
                    class="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-(--bg-secondary) rounded transition-all text-left">
                    <i :class="expandedNodes.has('top') ? 'ri-arrow-down-s-line' : 'ri-arrow-right-s-line'"
                      class="text-xs text-(--text-secondary)"></i>
                    <i class="ri-folder-fill text-yellow-500"></i>
                    <span class="text-[12px] font-semibold text-(--text-primary)">Top_Cell</span>
                  </button>

                  <div v-if="expandedNodes.has('top')" class="ml-4 space-y-0.5 mt-0.5">
                    <button
                      class="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-(--bg-secondary) rounded transition-all text-left group/item">
                      <i class="ri-arrow-right-s-line text-xs text-(--text-secondary)"></i>
                      <i class="ri-cpu-line text-blue-400"></i>
                      <span
                        class="text-[12px] text-(--text-secondary) group-hover/item:text-(--text-primary)">ALU_Core</span>
                    </button>
                    <!-- ... 其他节点 ... -->
                    <button
                      class="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-(--bg-secondary) rounded transition-all text-left group/item">
                      <i class="ri-arrow-right-s-line text-xs text-(--text-secondary)"></i>
                      <i class="ri-checkbox-blank-circle-line text-green-400"></i>
                      <span
                        class="text-[12px] text-(--text-secondary) group-hover/item:text-(--text-primary)">IO_Ring</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Files Tab -->
          <div v-else-if="activeTab === 'files'" class="h-full p-3">
            <!-- ... 原有内容 ... -->
            <div class="text-[11px] text-(--text-secondary) space-y-2">
              <div class="flex items-center gap-2 hover:text-(--text-primary) cursor-pointer">
                <i class="ri-file-code-line"></i>
                <span>design.v</span>
              </div>
              <div class="flex items-center gap-2 hover:text-(--text-primary) cursor-pointer">
                <i class="ri-file-text-line"></i>
                <span>constraints.sdc</span>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- 底部操作栏 (增强版) -->
      <div class="p-3 border-t border-(--border-color) bg-(--bg-secondary)/30">
        <button @click="handleRunFlow" :disabled="isLoading"
          class="w-full flex items-center justify-center gap-2 px-3 py-2 bg-(--accent-color) text-white text-[11px] font-bold rounded hover:brightness-110 active:scale-[0.98] transition-all disabled:opacity-50 shadow-lg shadow-(--accent-color)/20">
          <i :class="isLoading ? 'ri-loader-4-line animate-spin' : 'ri-play-fill'"></i>
          {{ isLoading ? 'RUNNING...' : 'RUN FLOW' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { invoke } from '@tauri-apps/api/core'
import { useTauri } from '@/composables/useTauri'

const { isInTauri, ensureTauri } = useTauri()

const route = useRoute()
const isLoading = ref(false)
const hasData = ref(false) // 新增：标记是否已有编译数据

// 标签页配置
const tabs = [
  { id: 'hierarchy', label: 'Navigator' },
  { id: 'files', label: 'Files' },
]

const activeTab = ref<'hierarchy' | 'files' | 'search'>('hierarchy')
const expandedNodes = ref<Set<string>>(new Set(['top', 'cache']))

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

const toggleNode = (nodeId: string) => {
  if (expandedNodes.value.has(nodeId)) {
    expandedNodes.value.delete(nodeId)
  } else {
    expandedNodes.value.add(nodeId)
  }
}

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
  console.log('Starting Python flow for route:', routeName)

  try {
    // 使用 call_python_func 调用 flow.py 的 run_flow 方法
    const result = await invoke('call_python_func', {
      scriptPath: 'flow.py',
      funcName: 'run_flow',
      args: {
        route_name: routeName
      }
    }) as { code: number, stdout: string, stderr: string }

    console.log('Python 返回的原始数据:', result)

    if (result.code === 0) {
      try {
        const data = JSON.parse(result.stdout)
        console.log('✅ Python 返回的 JSON 数据:', data)
      } catch (parseError) {
        console.error('❌ JSON 解析失败:', parseError)
        console.log('原始输出:', result.stdout)
      }
    } else {
      console.error(`❌ Python 执行失败 (Code ${result.code}):`, result.stderr)
    }
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

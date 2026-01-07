<template>
  <div class="flex h-full">
    <!-- 第一栏：流程步骤导航 -->
    <div class="w-[48px] shrink-0 bg-(--bg-sidebar) border-r border-(--border-color) flex flex-col py-2">
      <router-link v-for="stage in flowStages" :key="stage.path" :to="'/workspace/' + stage.path"
        class="flex flex-col items-center justify-center py-3  transition-all group relative" :class="[
          currentStage === stage.path
            ? 'text-(--accent-color)'
            : 'text-(--text-secondary) hover:text-(--text-primary)'
        ]">
        <!-- 选中状态的左侧指示条 -->
        <div v-if="currentStage === stage.path"
          class="absolute left-0 top-4 bottom-4 w-0.5 bg-(--accent-color) rounded-r"></div>

        <i :class="stage.icon" class="text-xl mb-1.5 transition-all"
          :style="{ color: currentStage === stage.path ? 'var(--accent-color)' : '' }"></i>
        <span class="text-[10px] font-medium text-center leading-tight">
          {{ stage.label }}
        </span>

        <!-- 完成状态指示点 -->
        <span v-if="stage.completed" class="absolute top-2 right-2 w-1.5 h-1.5 bg-green-500 rounded-full"></span>
      </router-link>
    </div>

    <!-- 第二栏：Navigator 面板 -->
    <div
      class="w-[220px] min-w-[180px] max-w-[280px] bg-(--bg-primary) border-r border-(--border-color) flex flex-col overflow-hidden shrink-0">
      <!-- 顶部标签栏 -->
      <div class="h-10 flex items-center border-b border-(--border-color) px-3 gap-1">
        <button v-for="tab in tabs" :key="tab.id" @click="activeTab = tab.id as 'hierarchy' | 'files' | 'search'"
          class="px-3 py-1.5 text-[11px] font-bold uppercase tracking-wide transition-all rounded" :class="[
            activeTab === tab.id
              ? 'text-white bg-(--accent-color) shadow-sm'
              : 'text-(--text-secondary) hover:text-(--text-primary) hover:bg-(--bg-secondary)'
          ]">
          {{ tab.label }}
        </button>

        <!-- 右侧菜单按钮 -->
        <div class="ml-auto">
          <button class="p-1 text-(--text-secondary) hover:text-(--text-primary) transition-colors">
            <i class="ri-more-2-fill"></i>
          </button>
        </div>
      </div>

      <!-- Navigator 内容区 -->
      <div class="flex-1 overflow-hidden">
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

          <!-- 层级树 -->
          <div class="flex-1 overflow-y-auto p-2">
            <div class="space-y-0.5">
              <!-- Top Cell -->
              <div class="group">
                <button @click="toggleNode('top')"
                  class="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-(--bg-secondary) rounded transition-all text-left">
                  <i :class="expandedNodes.has('top') ? 'ri-arrow-down-s-line' : 'ri-arrow-right-s-line'"
                    class="text-xs text-(--text-secondary)"></i>
                  <i class="ri-folder-fill text-yellow-500"></i>
                  <span class="text-[12px] font-semibold text-(--text-primary)">Top_Cell</span>
                </button>

                <!-- Children -->
                <div v-if="expandedNodes.has('top')" class="ml-4 space-y-0.5 mt-0.5">
                  <!-- ALU_Core -->
                  <button
                    class="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-(--bg-secondary) rounded transition-all text-left group/item">
                    <i class="ri-arrow-right-s-line text-xs text-(--text-secondary)"></i>
                    <i class="ri-cpu-line text-blue-400"></i>
                    <span
                      class="text-[12px] text-(--text-secondary) group-hover/item:text-(--text-primary)">ALU_Core</span>
                  </button>

                  <!-- FPU_Unit -->
                  <button
                    class="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-(--bg-secondary) rounded transition-all text-left group/item">
                    <i class="ri-arrow-right-s-line text-xs text-(--text-secondary)"></i>
                    <i class="ri-cpu-line text-blue-400"></i>
                    <span
                      class="text-[12px] text-(--text-secondary) group-hover/item:text-(--text-primary)">FPU_Unit</span>
                  </button>

                  <!-- Cache_L1 (with errors) -->
                  <div>
                    <button @click="toggleNode('cache')"
                      class="w-full flex items-center gap-2 px-2 py-1.5 bg-blue-500/10 border border-blue-500/30 rounded transition-all text-left group/item">
                      <i :class="expandedNodes.has('cache') ? 'ri-arrow-down-s-line' : 'ri-arrow-right-s-line'"
                        class="text-xs text-(--text-secondary)"></i>
                      <i class="ri-database-2-line text-blue-400"></i>
                      <span class="text-[12px] text-(--text-primary) font-medium">Cache_L1</span>
                      <i class="ri-error-warning-fill text-red-500 text-xs ml-auto"></i>
                    </button>

                    <!-- Cache errors -->
                    <div v-if="expandedNodes.has('cache')" class="ml-4 space-y-0.5 mt-0.5">
                      <button
                        class="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-red-500/10 rounded transition-all text-left group/item">
                        <i class="ri-close-circle-fill text-red-500 text-sm"></i>
                        <span class="text-[11px] text-red-400 font-medium">DRC_Violation_01</span>
                      </button>
                      <button
                        class="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-red-500/10 rounded transition-all text-left group/item">
                        <i class="ri-close-circle-fill text-red-500 text-sm"></i>
                        <span class="text-[11px] text-red-400 font-medium">DRC_Violation_02</span>
                      </button>
                    </div>
                  </div>

                  <!-- IO_Ring -->
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
          <div class="text-[11px] text-(--text-secondary) space-y-2">
            <div class="flex items-center gap-2 hover:text-(--text-primary) cursor-pointer">
              <i class="ri-file-code-line"></i>
              <span>design.v</span>
            </div>
            <div class="flex items-center gap-2 hover:text-(--text-primary) cursor-pointer">
              <i class="ri-file-text-line"></i>
              <span>constraints.sdc</span>
            </div>
            <div class="flex items-center gap-2 hover:text-(--text-primary) cursor-pointer">
              <i class="ri-folder-line"></i>
              <span>reports/</span>
            </div>
          </div>
        </div>

        <!-- Search Tab -->
        <div v-else-if="activeTab === 'search'" class="h-full flex flex-col">
          <div class="p-3">
            <input type="text" placeholder="Search modules, nets, instances..."
              class="w-full px-3 py-2 text-[12px] bg-(--bg-secondary) border border-(--border-color) rounded text-(--text-primary) placeholder-text-(--text-secondary) focus:outline-none focus:border-(--accent-color)" />
          </div>
          <div class="flex-1 px-3 text-[11px] text-(--text-secondary)">
            <p class="opacity-60">No search results</p>
          </div>
        </div>
      </div>

      <!-- 底部操作栏 (可选) -->
      <div class="h-10 border-t border-(--border-color) flex items-center px-3 gap-2">
        <button
          class="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 bg-(--accent-color) text-white text-[11px] font-bold rounded hover:opacity-90 transition-all">
          <i class="ri-play-fill"></i>
          RUN FLOW
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

// 标签页配置
const tabs = [
  { id: 'hierarchy', label: 'Navigator' },
  { id: 'files', label: 'Files' },
]

const activeTab = ref<'hierarchy' | 'files' | 'search'>('hierarchy')
const expandedNodes = ref<Set<string>>(new Set(['top', 'cache']))

// 流程步骤配置
const flowStages = [
  { label: 'Home', path: 'home', icon: 'ri-home-4-line', group: 'setup', completed: false },
  { label: 'Config', path: 'configure', icon: 'ri-settings-3-line', group: 'setup', completed: false },
  { label: 'Synth', path: 'synthesis', icon: 'ri-node-tree', group: 'run', completed: true },
  { label: 'Floor', path: 'floorplan', icon: 'ri-layout-4-line', group: 'run', completed: true },
  { label: 'Place', path: 'place', icon: 'ri-focus-2-line', group: 'run', completed: false },
  { label: 'CTS', path: 'cts', icon: 'ri-git-merge-line', group: 'run', completed: false },
  { label: 'Route', path: 'route', icon: 'ri-route-line', group: 'run', completed: false },
  { label: 'Signoff', path: 'signoff', icon: 'ri-checkbox-circle-line', group: 'run', completed: false }
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

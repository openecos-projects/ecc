<template>
  <div class="home-view">
    <!-- 背景装饰 -->
    <div class="bg-grid"></div>

    <!-- ===== Dashboard Grid ===== -->
    <div class="dashboard-grid">

      <!-- ========== Row 1 Left: Chip Basic Info / Spec ========== -->
      <section class="section-card chip-info-area">
        <div class="section-header">
          <div class="header-icon"><i class="ri-cpu-line"></i></div>
          <h2>Chip Basic Info / Spec</h2>
          <span class="header-badge" v-if="config.pdk">{{ config.pdk }}</span>
        </div>
        <div class="chip-info-content">
          <div class="info-grid">
            <div class="info-item">
              <span class="info-label">Design</span>
              <span class="info-value highlight">{{ config.design || '--' }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">Top Module</span>
              <span class="info-value mono">{{ config.topModule || '--' }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">Die Size</span>
              <span class="info-value mono">{{ formatBBox(config.die?.boundingBox) }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">Core Size</span>
              <span class="info-value mono">{{ formatBBox(config.core?.boundingBox) }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">Frequency</span>
              <span class="info-value">{{ config.frequencyMax || '--' }} <small>MHz</small></span>
            </div>
            <div class="info-item">
              <span class="info-label">Utilization</span>
              <span class="info-value">{{ ((config.core?.utilization || 0) * 100).toFixed(0) }}%</span>
            </div>
            <div class="info-item">
              <span class="info-label">Clock</span>
              <span class="info-value">{{ config.clock || '--' }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">Layers</span>
              <span class="info-value">{{ config.bottomLayer }} - {{ config.topLayer }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- ========== Row 1 Right: 运行时监控 ========== -->
      <section class="section-card monitor-area">
        <div class="section-header">
          <div class="header-icon monitor"><i class="ri-pulse-line"></i></div>
          <h2>运行时监控</h2>
        </div>
        <div class="monitor-content" v-if="monitorData">
          <div v-for="cfg in chartConfigs" :key="cfg.key" class="monitor-row">
            <span class="monitor-label">{{ cfg.label }}</span>
            <div class="monitor-chart-wrap">
              <div
                :ref="(el: any) => { if (cfg.key === 'memory') memoryChartRef = el; else if (cfg.key === 'runtime') runtimeChartRef = el; else if (cfg.key === 'instance') instanceChartRef = el; else if (cfg.key === 'frequency') frequencyChartRef = el; }"
                class="monitor-chart"
              ></div>
            </div>
            <span class="monitor-value">{{ getMetricMax(cfg.key) }}</span>
          </div>
        </div>
        <div v-else class="monitor-content">
          <div class="monitor-placeholder">
            <i class="ri-pulse-line"></i>
            <p>No monitor data</p>
            <span>运行流程后显示监控数据</span>
          </div>
        </div>
      </section>

      <!-- ========== Row 2 Left+Center: Layout Preview ========== -->
      <section class="section-card layout-area">
        <div class="section-header">
          <div class="header-icon layout"><i class="ri-layout-masonry-line"></i></div>
          <h2>Layout</h2>
          <span class="header-hint">显示跑通过的最后 step 版图</span>
          <div class="header-actions">
            <button class="action-btn"><i class="ri-zoom-in-line"></i></button>
            <button class="action-btn"><i class="ri-zoom-out-line"></i></button>
            <button class="action-btn"><i class="ri-fullscreen-line"></i></button>
          </div>
        </div>
        <div class="layout-content">
          <img
            v-if="layoutBlobUrl"
            :src="layoutBlobUrl"
            alt="Layout Preview"
            class="layout-image"
          />
          <div v-else class="layout-placeholder">
            <i class="ri-image-2-line"></i>
            <p>Layout Preview</p>
            <span>等待版图数据...</span>
          </div>
        </div>
      </section>

      <!-- ========== Row 2 Right: 指标分析 ========== -->
      <section class="section-card analysis-area">
        <div class="section-header">
          <div class="header-icon analysis"><i class="ri-pie-chart-line"></i></div>
          <h2>指标分析</h2>
        </div>
        <div class="analysis-content">
          <div class="charts-grid">
            <div class="chart-card" v-for="chart in analysisCharts" :key="chart.label">
              <div class="chart-visual">
                <i :class="chart.icon"></i>
              </div>
              <span class="chart-label">{{ chart.label }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- ========== Row 3 Left: GDS Merge ========== -->
      <section class="section-card gds-area">
        <div class="section-header">
          <div class="header-icon gds"><i class="ri-layout-grid-line"></i></div>
          <h2>GDS Merge</h2>
        </div>
        <div class="gds-content">
          <div class="gds-chip-diagram">
            <div class="gds-title">ACTIVE</div>
            <div class="gds-blocks-grid">
              <div class="gds-block core">CORE</div>
              <div class="gds-block rcu">RCU</div>
              <div class="gds-block bus-row">
                <span class="gds-bus-dot"></span>
                <span>BUS</span>
              </div>
              <div class="gds-block">SPIFS</div>
              <div class="gds-block">UART</div>
              <div class="gds-block">QSPI</div>
              <div class="gds-block">PSRAM</div>
              <div class="gds-block">GPIO</div>
              <div class="gds-block">TIMER</div>
              <div class="gds-block">I2C</div>
              <div class="gds-block">PWM</div>
            </div>
          </div>
        </div>
      </section>

      <!-- ========== Row 3 Right: Checklist Table ========== -->
      <section class="section-card checklist-area">
        <div class="section-header">
          <div class="header-icon checklist"><i class="ri-checkbox-multiple-line"></i></div>
          <h2>Checklist Table</h2>
          <span class="header-count">{{ checklistCompletedCount }}/{{ checklistItems.length }}</span>
        </div>
        <div class="checklist-content">
          <!-- Table format -->
          <div class="checklist-table-wrap" v-if="checklistItems.length > 0">
            <table class="checklist-table">
              <thead>
                <tr>
                  <th>步骤/阶段</th>
                  <th>验证类型</th>
                  <th>验收条件</th>
                  <th>验收结果</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(item, idx) in checklistItems" :key="idx" :class="stateClass(item.state)">
                  <td>
                    <div class="table-step-name">
                      <i class="ri-checkbox-blank-circle-line table-step-icon"></i>
                      {{ item.step }}
                    </div>
                  </td>
                  <td class="table-tool">{{ item.type }}</td>
                  <td class="table-criteria">{{ item.item }}</td>
                  <td>
                    <span class="table-state-tag" :class="stateClass(item.state)">
                      <i :class="stateIcon(item.state)" class="table-state-icon"></i>
                      {{ stateLabel(item.state) }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <!-- Empty state -->
          <div class="checklist-placeholder" v-else>
            <i class="ri-list-check-2"></i>
            <p>No checklist items</p>
            <span>运行流程后显示检查项</span>
          </div>
        </div>
      </section>

    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick, type Ref } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useParameters } from '@/composables/useParameters'
import { useHomeData } from '@/composables/useHomeData'

// 注册 ECharts 组件（按需引入）
echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const { config } = useParameters()
const { monitorData, checklistItems, layoutBlobUrl } = useHomeData()

// checklist 完成计数
const checklistCompletedCount = computed(() =>
  checklistItems.value.filter(c => c.state === 'Success').length
)

// ============ ECharts 折线图 ============

// 4 个图表容器 ref
const memoryChartRef = ref<HTMLDivElement>()
const runtimeChartRef = ref<HTMLDivElement>()
const instanceChartRef = ref<HTMLDivElement>()
const frequencyChartRef = ref<HTMLDivElement>()

// ECharts 实例
let memoryChart: echarts.ECharts | null = null
let runtimeChart: echarts.ECharts | null = null
let instanceChart: echarts.ECharts | null = null
let frequencyChart: echarts.ECharts | null = null

// ResizeObserver
let resizeObserver: ResizeObserver | null = null

/** 将 runtime 字符串 "h:m:s" 转换为秒数 */
function parseRuntimeToSeconds(runtime: string): number {
  const parts = runtime.split(':').map(Number)
  if (parts.length === 3) {
    return parts[0] * 3600 + parts[1] * 60 + parts[2]
  }
  return 0
}

/** 图表配色方案 */
const chartConfigs = [
  { label: 'Memory (MB)', color: '#ef4444', ref: memoryChartRef, key: 'memory' as const },
  { label: 'Runtime (s)', color: '#3b82f6', ref: runtimeChartRef, key: 'runtime' as const },
  { label: 'Instance', color: '#10b981', ref: instanceChartRef, key: 'instance' as const },
  { label: 'Frequency (MHz)', color: '#a855f7', ref: frequencyChartRef, key: 'frequency' as const },
]

/** 获取某个维度的数值数组 */
function getMetricValues(key: string): number[] {
  if (!monitorData.value) return []
  const raw = monitorData.value[key as keyof typeof monitorData.value]
  if (!raw || !Array.isArray(raw)) return []

  if (key === 'runtime') {
    return (raw as string[]).map(parseRuntimeToSeconds)
  }
  if (key === 'memory') {
    return (raw as string[]).map(Number)
  }
  return raw as number[]
}

/** 获取某个维度的最大值显示 */
function getMetricMax(key: string): string {
  const values = getMetricValues(key)
  if (values.length === 0) return '--'
  const max = Math.max(...values)
  if (key === 'memory') return `${max.toFixed(1)} MB`
  if (key === 'runtime') return `${max}s`
  if (key === 'frequency') return `${max.toFixed(1)} MHz`
  return `${max}`
}

/** 构建单个迷你折线图的 option */
function buildChartOption(key: string, color: string): echarts.EChartsCoreOption {
  const values = getMetricValues(key)
  const steps = monitorData.value?.step || []

  return {
    grid: {
      left: 4,
      right: 4,
      top: 4,
      bottom: 4,
      containLabel: false,
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(30, 30, 30, 0.9)',
      borderColor: color,
      borderWidth: 1,
      textStyle: {
        color: '#e5e5e5',
        fontSize: 10,
      },
      formatter: (params: any) => {
        const idx = params[0]?.dataIndex ?? 0
        const stepName = steps[idx] || `#${idx}`
        const val = params[0]?.value ?? 0
        let unit = ''
        if (key === 'memory') unit = ' MB'
        else if (key === 'runtime') unit = 's'
        else if (key === 'frequency') unit = ' MHz'
        return `<div style="font-size:10px;font-weight:600;margin-bottom:2px">${stepName}</div>
                <span style="color:${color}">${val}${unit}</span>`
      },
    },
    xAxis: {
      type: 'category',
      show: false,
      data: values.map((_, i) => i),
      boundaryGap: false,
    },
    yAxis: {
      type: 'value',
      show: false,
    },
    series: [
      {
        type: 'line',
        data: values,
        smooth: 0.3,
        symbol: 'none',
        lineStyle: {
          color,
          width: 1.5,
        },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: color + '40' },
            { offset: 1, color: color + '05' },
          ]),
        },
      },
    ],
    animation: true,
    animationDuration: 600,
  }
}

/** 初始化或更新所有图表 */
function initOrUpdateCharts() {
  const chartPairs: Array<{
    ref: Ref<HTMLDivElement | undefined>
    getInstance: () => echarts.ECharts | null
    setInstance: (c: echarts.ECharts) => void
    key: string
    color: string
  }> = [
    { ref: memoryChartRef, getInstance: () => memoryChart, setInstance: (c) => memoryChart = c, key: 'memory', color: '#ef4444' },
    { ref: runtimeChartRef, getInstance: () => runtimeChart, setInstance: (c) => runtimeChart = c, key: 'runtime', color: '#3b82f6' },
    { ref: instanceChartRef, getInstance: () => instanceChart, setInstance: (c) => instanceChart = c, key: 'instance', color: '#10b981' },
    { ref: frequencyChartRef, getInstance: () => frequencyChart, setInstance: (c) => frequencyChart = c, key: 'frequency', color: '#a855f7' },
  ]

  for (const { ref: chartRef, getInstance, setInstance, key, color } of chartPairs) {
    if (!chartRef.value) continue

    let instance = getInstance()
    if (!instance) {
      instance = echarts.init(chartRef.value, undefined, { renderer: 'canvas' })
      setInstance(instance)
    }

    instance.setOption(buildChartOption(key, color), true)
  }
}

/** 销毁所有图表 */
function disposeCharts() {
  memoryChart?.dispose(); memoryChart = null
  runtimeChart?.dispose(); runtimeChart = null
  instanceChart?.dispose(); instanceChart = null
  frequencyChart?.dispose(); frequencyChart = null
}

/** 所有图表 resize */
function resizeAllCharts() {
  memoryChart?.resize()
  runtimeChart?.resize()
  instanceChart?.resize()
  frequencyChart?.resize()
}

// 监听 monitorData 变化，更新图表
watch(
  () => monitorData.value,
  async () => {
    await nextTick()
    initOrUpdateCharts()
  },
  { deep: true }
)

onMounted(async () => {
  await nextTick()
  if (monitorData.value) {
    initOrUpdateCharts()
  }

  // ResizeObserver 响应容器变化
  resizeObserver = new ResizeObserver(() => {
    resizeAllCharts()
  })
  if (memoryChartRef.value?.parentElement) {
    resizeObserver.observe(memoryChartRef.value.parentElement)
  }
})

onUnmounted(() => {
  disposeCharts()
  resizeObserver?.disconnect()
  resizeObserver = null
})

// ============ 指标分析图表占位 ============
const analysisCharts = [
  { label: '单元分布', icon: 'ri-pie-chart-line' },
  { label: '层分布', icon: 'ri-bar-chart-grouped-line' },
  { label: '层分布', icon: 'ri-bar-chart-line' },
  { label: 'Net-Pins分布', icon: 'ri-bar-chart-2-line' },
  { label: 'DRC类型分布', icon: 'ri-donut-chart-line' },
  { label: 'DRC层分布', icon: 'ri-bar-chart-horizontal-line' },
  { label: 'CTS Skew map', icon: 'ri-line-chart-line' }
]

// ============ 辅助函数 ============

/** 根据步骤状态返回图标类名 */
function stateIcon(state: string): string {
  switch (state) {
    case 'Success':
      return 'ri-checkbox-circle-fill'
    case 'Ongoing':
      return 'ri-loader-4-line spin'
    case 'Imcomplete':
      return 'ri-close-circle-fill'
    case 'Pending':
      return 'ri-time-line'
    case 'Unstart':
    default:
      return 'ri-checkbox-blank-circle-line'
  }
}

/** 根据步骤状态返回 CSS 类名 */
function stateClass(state: string): string {
  switch (state) {
    case 'Success':
      return 'state-success'
    case 'Ongoing':
      return 'state-ongoing'
    case 'Imcomplete':
      return 'state-failed'
    case 'Pending':
      return 'state-pending'
    case 'Unstart':
    default:
      return 'state-unstart'
  }
}

/** 根据步骤状态返回中文标签 */
function stateLabel(state: string): string {
  switch (state) {
    case 'Success':
      return '已完成'
    case 'Ongoing':
      return '运行中'
    case 'Imcomplete':
      return '失败'
    case 'Pending':
      return '等待中'
    case 'Unstart':
    default:
      return '未开始'
  }
}

/** 格式化 Bounding Box 显示 */
function formatBBox(bbox: string | undefined): string {
  if (!bbox) return '--'
  const match = bbox.match(/\((\d+),(\d+),(\d+),(\d+)\)/)
  if (match) {
    const w = parseInt(match[3]) - parseInt(match[1])
    const h = parseInt(match[4]) - parseInt(match[2])
    return `${w}x${h}`
  }
  return bbox
}

</script>

<style scoped>
/* ==================== 基础布局 ==================== */
.home-view {
  height: 100%;
  position: relative;
  overflow: hidden;
  background: var(--bg-primary);
}

.bg-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(var(--accent-rgb, 59, 130, 246), 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--accent-rgb, 59, 130, 246), 0.03) 1px, transparent 1px);
  background-size: 32px 32px;
  pointer-events: none;
}

/* ==================== Dashboard Grid ==================== */
.dashboard-grid {
  position: relative;
  z-index: 1;
  height: 100%;
  display: grid;
  grid-template-columns: 1fr 1.2fr;
  grid-template-rows: auto 1fr 0.7fr;
  grid-template-areas:
    "info      monitor"
    "layout    analysis"
    "gds       checklist";
  gap: 8px;
  padding: 8px;
}

/* Grid Area Assignments */
.chip-info-area   { grid-area: info; }
.monitor-area     { grid-area: monitor; }
.layout-area      { grid-area: layout; }
.analysis-area    { grid-area: analysis; }
.gds-area         { grid-area: gds; }
.checklist-area   { grid-area: checklist; }

/* ==================== Section Card 通用样式 ==================== */
.section-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
  min-height: 0;
}

/* Section Header */
.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: linear-gradient(135deg, var(--bg-sidebar) 0%, var(--bg-secondary) 100%);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.header-icon {
  width: 24px;
  height: 24px;
  background: linear-gradient(135deg, var(--accent-color) 0%, #06b6d4 100%);
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 12px;
  flex-shrink: 0;
}

.section-header h2 {
  flex: 1;
  font-size: 11px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.header-badge {
  padding: 2px 7px;
  background: linear-gradient(135deg, var(--accent-color) 0%, #06b6d4 100%);
  color: white;
  font-size: 9px;
  font-weight: 700;
  border-radius: 4px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  flex-shrink: 0;
}

.header-hint {
  font-size: 9px;
  color: var(--text-secondary);
  opacity: 0.7;
  white-space: nowrap;
}

.header-count {
  padding: 2px 7px;
  background: var(--bg-primary);
  color: var(--text-secondary);
  font-size: 10px;
  font-weight: 600;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  flex-shrink: 0;
}

.header-actions {
  display: flex;
  gap: 3px;
  flex-shrink: 0;
}

.action-btn {
  width: 22px;
  height: 22px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  background: var(--bg-primary);
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s ease;
  font-size: 11px;
}

.action-btn:hover {
  border-color: var(--accent-color);
  color: var(--accent-color);
}

/* ==================== Chip Basic Info ==================== */
.chip-info-content {
  flex: 1;
  padding: 10px;
  overflow: auto;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
  height: 100%;
}

.info-item {
  padding: 8px 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  transition: border-color 0.15s ease;
}

.info-item:hover {
  border-color: var(--accent-color);
}

.info-label {
  font-size: 9px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 3px;
}

.info-value {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
}

.info-value.highlight {
  color: var(--accent-color);
}

.info-value.mono {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}

.info-value small {
  font-size: 9px;
  font-weight: 500;
  opacity: 0.7;
}

/* ==================== 运行时监控 ==================== */
.monitor-content {
  flex: 1;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow: auto;
}

.monitor-row {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  min-height: 0;
}

.monitor-label {
  width: 100px;
  font-size: 9px;
  font-weight: 600;
  color: var(--text-secondary);
  white-space: nowrap;
  flex-shrink: 0;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.monitor-chart-wrap {
  flex: 1;
  height: 100%;
  min-height: 24px;
  min-width: 0;
}

.monitor-chart {
  width: 100%;
  height: 100%;
  min-height: 24px;
}

.monitor-value {
  min-width: 80px;
  text-align: right;
  font-size: 10px;
  font-weight: 700;
  color: var(--text-primary);
  font-family: 'JetBrains Mono', monospace;
  flex-shrink: 0;
}

.monitor-placeholder {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 20px;
  border: 2px dashed var(--border-color);
  border-radius: 8px;
  background: var(--bg-primary);
}

.monitor-placeholder i {
  font-size: 28px;
  color: var(--text-secondary);
  opacity: 0.3;
}

.monitor-placeholder p {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin: 0;
}

.monitor-placeholder span {
  font-size: 10px;
  color: var(--text-secondary);
  opacity: 0.6;
}

/* ==================== Layout Preview ==================== */
.layout-content {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
  margin: 8px;
  border-radius: 6px;
  overflow: hidden;
}

.layout-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  border: 2px dashed var(--border-color);
  border-radius: 8px;
  background:
    linear-gradient(90deg, rgba(var(--accent-rgb, 59, 130, 246), 0.02) 1px, transparent 1px),
    linear-gradient(rgba(var(--accent-rgb, 59, 130, 246), 0.02) 1px, transparent 1px);
  background-size: 16px 16px;
}

.layout-placeholder i {
  font-size: 36px;
  color: var(--text-secondary);
  opacity: 0.3;
}

.layout-placeholder p {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin: 0;
}

.layout-placeholder span {
  font-size: 10px;
  color: var(--text-secondary);
  opacity: 0.6;
}

.layout-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

/* ==================== 指标分析 ==================== */
.analysis-content {
  flex: 1;
  padding: 8px;
  overflow: auto;
}

.charts-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  grid-template-rows: 1fr 1fr;
  gap: 6px;
  height: 100%;
}

/* Last row has 3 charts - span adjustment */
.chart-card:nth-child(5) { grid-column: 1; }
.chart-card:nth-child(6) { grid-column: 2; }
.chart-card:nth-child(7) { grid-column: 3 / 5; }

.chart-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px;
  transition: border-color 0.15s ease;
  cursor: pointer;
  overflow: hidden;
}

.chart-card:hover {
  border-color: var(--accent-color);
}

.chart-visual {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  color: var(--text-secondary);
  opacity: 0.25;
}

.chart-label {
  font-size: 9px;
  font-weight: 600;
  color: var(--text-secondary);
  text-align: center;
  white-space: nowrap;
}

/* ==================== GDS Merge ==================== */
.gds-content {
  flex: 1;
  padding: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: auto;
}

.gds-chip-diagram {
  background: var(--bg-primary);
  border: 2px solid var(--border-color);
  border-radius: 8px;
  padding: 12px;
  min-width: 280px;
  max-width: 420px;
  width: 100%;
}

.gds-title {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 8px;
}

.gds-blocks-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 4px;
}

.gds-block {
  padding: 8px 6px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  text-align: center;
  font-size: 9px;
  font-weight: 700;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  transition: all 0.15s ease;
}

.gds-block:hover {
  border-color: var(--accent-color);
  color: var(--accent-color);
}

.gds-block.core {
  grid-column: 1 / 3;
  grid-row: 1 / 3;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(var(--accent-rgb, 59, 130, 246), 0.08);
  border-color: var(--accent-color);
  color: var(--accent-color);
  font-size: 11px;
}

.gds-block.rcu {
  grid-column: 3 / 5;
}

.gds-block.bus-row {
  grid-column: 1 / 5;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.gds-bus-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--accent-color);
}

/* ==================== Checklist Table ==================== */
.checklist-content {
  flex: 1;
  padding: 8px;
  overflow: auto;
}

.checklist-table-wrap {
  height: 100%;
  overflow: auto;
}

.checklist-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 10px;
}

.checklist-table thead th {
  position: sticky;
  top: 0;
  background: var(--bg-sidebar);
  padding: 6px 8px;
  text-align: left;
  font-weight: 700;
  font-size: 9px;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border-bottom: 1px solid var(--border-color);
  white-space: nowrap;
}

.checklist-table tbody td {
  padding: 5px 8px;
  border-bottom: 1px solid var(--border-color);
  color: var(--text-primary);
  vertical-align: middle;
}

.checklist-table tbody tr {
  transition: background 0.1s ease;
}

.checklist-table tbody tr:hover {
  background: rgba(var(--accent-rgb, 59, 130, 246), 0.04);
}

.table-step-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  white-space: nowrap;
}

.table-step-icon {
  font-size: 12px;
  color: var(--text-secondary);
}

.table-tool,
.table-criteria {
  color: var(--text-secondary);
  font-size: 10px;
}

.table-state-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  font-size: 9px;
  font-weight: 600;
  border-radius: 3px;
  white-space: nowrap;
}

.table-state-icon {
  font-size: 11px;
}

.table-state-tag.state-success {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.table-state-tag.state-ongoing {
  background: rgba(59, 130, 246, 0.15);
  color: #3b82f6;
}

.table-state-tag.state-failed {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.table-state-tag.state-pending {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}

.table-state-tag.state-unstart {
  background: var(--bg-secondary);
  color: var(--text-secondary);
  opacity: 0.6;
}

/* Empty state */
.checklist-placeholder {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 20px;
  border: 2px dashed var(--border-color);
  border-radius: 8px;
  background: var(--bg-primary);
}

.checklist-placeholder i {
  font-size: 28px;
  color: var(--text-secondary);
  opacity: 0.3;
}

.checklist-placeholder p {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin: 0;
}

.checklist-placeholder span {
  font-size: 10px;
  color: var(--text-secondary);
  opacity: 0.6;
}

/* ==================== 通用动画 ==================== */
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.spin {
  animation: spin 1s linear infinite;
}

/* ==================== 响应式 ==================== */
@media (max-width: 1200px) {
  .dashboard-grid {
    grid-template-columns: 1fr 1fr;
  }

  .info-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .charts-grid {
    grid-template-columns: repeat(3, 1fr);
  }

  .chart-card:nth-child(7) {
    grid-column: 3;
  }
}

@media (max-width: 900px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
    grid-template-rows: auto;
    grid-template-areas:
      "info"
      "monitor"
      "layout"
      "analysis"
      "gds"
      "checklist";
    overflow-y: auto;
  }

  .section-card {
    min-height: 200px;
  }
}
</style>

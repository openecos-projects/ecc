<template>
  <div class="home-view">
    <!-- 背景装饰 -->
    <div class="bg-grid"></div>
    <div class="bg-glow"></div>

    <!-- 主内容区：左右均分 -->
    <div class="main-content">
      <!-- ========== 左侧区域 ========== -->
      <div class="left-panel">
        <!-- Chip Basic Info (高度 1/5) -->
        <section class="chip-info-section">
          <div class="section-header">
            <div class="header-icon">
              <i class="ri-cpu-line"></i>
            </div>
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

        <!-- Layout 版图 (高度 2/5) -->
        <section class="layout-section">
          <div class="section-header">
            <div class="header-icon">
              <i class="ri-layout-masonry-line"></i>
            </div>
            <h2>Layout</h2>
            <span class="header-hint">显示跑通过的最后 step 版图</span>
            <div class="header-actions">
              <button class="action-btn"><i class="ri-zoom-in-line"></i></button>
              <button class="action-btn"><i class="ri-zoom-out-line"></i></button>
              <button class="action-btn"><i class="ri-fullscreen-line"></i></button>
            </div>
          </div>
          <div class="layout-content">
            <div class="layout-placeholder">
              <i class="ri-image-2-line"></i>
              <p>Layout Preview</p>
              <span>等待版图数据...</span>
            </div>
          </div>
        </section>

        <!-- 关键分析信息区 (高度 2/5) -->
        <section class="analysis-section">
          <div class="section-header">
            <div class="header-icon">
              <i class="ri-bar-chart-grouped-line"></i>
            </div>
            <h2>关键分析信息区</h2>
          </div>
          <div class="analysis-content">
            <div class="analysis-grid">
              <!-- Timing -->
              <div class="analysis-card timing">
                <div class="card-glow"></div>
                <div class="card-icon"><i class="ri-timer-flash-line"></i></div>
                <div class="card-info">
                  <span class="card-label">Timing</span>
                  <span class="card-value">--</span>
                  <span class="card-unit">ns</span>
                </div>
              </div>
              <!-- Power -->
              <div class="analysis-card power">
                <div class="card-glow"></div>
                <div class="card-icon"><i class="ri-flashlight-line"></i></div>
                <div class="card-info">
                  <span class="card-label">Power</span>
                  <span class="card-value">--</span>
                  <span class="card-unit">mW</span>
                </div>
              </div>
              <!-- Area -->
              <div class="analysis-card area">
                <div class="card-glow"></div>
                <div class="card-icon"><i class="ri-shape-2-line"></i></div>
                <div class="card-info">
                  <span class="card-label">Area</span>
                  <span class="card-value">--</span>
                  <span class="card-unit">um²</span>
                </div>
              </div>
              <!-- DRC -->
              <div class="analysis-card drc">
                <div class="card-glow"></div>
                <div class="card-icon"><i class="ri-shield-check-line"></i></div>
                <div class="card-info">
                  <span class="card-label">DRC</span>
                  <span class="card-value">--</span>
                  <span class="card-unit">errors</span>
                </div>
              </div>
              <!-- Congestion -->
              <div class="analysis-card congestion">
                <div class="card-glow"></div>
                <div class="card-icon"><i class="ri-traffic-light-line"></i></div>
                <div class="card-info">
                  <span class="card-label">Congestion</span>
                  <span class="card-value">--</span>
                  <span class="card-unit">%</span>
                </div>
              </div>
              <!-- Wirelength -->
              <div class="analysis-card wirelength">
                <div class="card-glow"></div>
                <div class="card-icon"><i class="ri-route-line"></i></div>
                <div class="card-info">
                  <span class="card-label">Wirelength</span>
                  <span class="card-value">--</span>
                  <span class="card-unit">um</span>
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>

      <!-- ========== 右侧区域 ========== -->
      <div class="right-panel">
        <!-- 数据趋势变化图 (高度 1/2) -->
        <section class="metrics-section">
          <div class="section-header">
            <div class="header-icon">
              <i class="ri-line-chart-line"></i>
            </div>
            <h2>数据趋势变化图</h2>
          </div>
          <div class="metrics-content">
            <div class="metrics-list">
              <div class="metric-item">
                <div class="metric-indicator memory"></div>
                <span class="metric-label">Memory</span>
                <span class="metric-value">--</span>
                <div class="metric-chart">
                  <div class="chart-placeholder"></div>
                </div>
              </div>
              <div class="metric-item">
                <div class="metric-indicator core"></div>
                <span class="metric-label">Core 利用率</span>
                <span class="metric-value">--</span>
                <div class="metric-chart">
                  <div class="chart-placeholder"></div>
                </div>
              </div>
              <div class="metric-item">
                <div class="metric-indicator cells"></div>
                <span class="metric-label">单元个数</span>
                <span class="metric-value">--</span>
                <div class="metric-chart">
                  <div class="chart-placeholder"></div>
                </div>
              </div>
              <div class="metric-item">
                <div class="metric-indicator nets"></div>
                <span class="metric-label">Net 个数</span>
                <span class="metric-value">--</span>
                <div class="metric-chart">
                  <div class="chart-placeholder"></div>
                </div>
              </div>
              <div class="metric-item">
                <div class="metric-indicator timing"></div>
                <span class="metric-label">时序</span>
                <span class="metric-value">--</span>
                <div class="metric-chart">
                  <div class="chart-placeholder"></div>
                </div>
              </div>
              <div class="metric-item">
                <div class="metric-indicator wire"></div>
                <span class="metric-label">线长</span>
                <span class="metric-value">--</span>
                <div class="metric-chart">
                  <div class="chart-placeholder"></div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- Checklist (高度 1/2) -->
        <section class="checklist-section">
          <div class="section-header">
            <div class="header-icon">
              <i class="ri-checkbox-multiple-line"></i>
            </div>
            <h2>Checklist</h2>
            <span class="header-count">0/0</span>
          </div>
          <div class="checklist-content">
            <div class="checklist-placeholder">
              <i class="ri-list-check-2"></i>
              <p>No checklist items</p>
              <span>运行流程后显示检查项</span>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useParameters } from '@/composables/useParameters'

const { config } = useParameters()

// 格式化 Bounding Box 显示
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

/* 科技感背景网格 */
.bg-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(var(--accent-rgb, 59, 130, 246), 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--accent-rgb, 59, 130, 246), 0.03) 1px, transparent 1px);
  background-size: 32px 32px;
  pointer-events: none;
}

.bg-glow {
  position: absolute;
  top: -150px;
  right: -150px;
  width: 400px;
  height: 400px;
  background: radial-gradient(circle, rgba(var(--accent-rgb, 59, 130, 246), 0.1) 0%, transparent 70%);
  pointer-events: none;
}

/* 主内容：左右均分 */
.main-content {
  position: relative;
  z-index: 1;
  height: 100%;
  display: flex;
  gap: 12px;
  padding: 12px;
}

/* 左侧面板 */
.left-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

/* 右侧面板 */
.right-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

/* ==================== 通用 Section 样式 ==================== */
.chip-info-section,
.layout-section,
.analysis-section,
.metrics-section,
.checklist-section {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 高度分配 - 左侧 1:2:2 */
.chip-info-section {
  flex: 1;
}

.layout-section {
  flex: 1;
}

.analysis-section {
  flex: 2;
}

/* 高度分配 - 右侧 1:1 */
.metrics-section {
  flex: 1;
}

.checklist-section {
  flex: 1;
}

/* Section Header */
.section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: linear-gradient(135deg, var(--bg-sidebar) 0%, var(--bg-secondary) 100%);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.header-icon {
  width: 28px;
  height: 28px;
  background: linear-gradient(135deg, var(--accent-color) 0%, #06b6d4 100%);
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 14px;
  box-shadow: 0 2px 8px rgba(var(--accent-rgb, 59, 130, 246), 0.3);
}

.section-header h2 {
  flex: 1;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.header-badge {
  padding: 3px 8px;
  background: linear-gradient(135deg, var(--accent-color) 0%, #06b6d4 100%);
  color: white;
  font-size: 9px;
  font-weight: 700;
  border-radius: 4px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.header-hint {
  font-size: 10px;
  color: var(--text-secondary);
  opacity: 0.7;
}

.header-count {
  padding: 2px 8px;
  background: var(--bg-primary);
  color: var(--text-secondary);
  font-size: 10px;
  font-weight: 600;
  border-radius: 4px;
  border: 1px solid var(--border-color);
}

.header-actions {
  display: flex;
  gap: 4px;
}

.action-btn {
  width: 24px;
  height: 24px;
  border: 1px solid var(--border-color);
  border-radius: 5px;
  background: var(--bg-primary);
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s ease;
  font-size: 12px;
}

.action-btn:hover {
  border-color: var(--accent-color);
  color: var(--accent-color);
  background: rgba(var(--accent-rgb, 59, 130, 246), 0.1);
}

/* ==================== Chip Info Section ==================== */
.chip-info-content {
  flex: 1;
  padding: 12px;
  overflow: auto;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  height: 100%;
}

.info-item {
  padding: 10px 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  transition: all 0.15s ease;
}

.info-item:hover {
  border-color: var(--accent-color);
}

.info-label {
  font-size: 9px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 4px;
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

/* ==================== Layout Section ==================== */
.layout-content {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
  margin: 10px;
  border-radius: 8px;
  overflow: hidden;
}

.layout-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px;
  border: 2px dashed var(--border-color);
  border-radius: 10px;
  background:
    linear-gradient(90deg, rgba(var(--accent-rgb, 59, 130, 246), 0.02) 1px, transparent 1px),
    linear-gradient(rgba(var(--accent-rgb, 59, 130, 246), 0.02) 1px, transparent 1px);
  background-size: 16px 16px;
}

.layout-placeholder i {
  font-size: 40px;
  color: var(--text-secondary);
  opacity: 0.3;
}

.layout-placeholder p {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin: 0;
}

.layout-placeholder span {
  font-size: 10px;
  color: var(--text-secondary);
  opacity: 0.6;
}

/* ==================== Analysis Section ==================== */
.analysis-content {
  flex: 1;
  padding: 12px;
  overflow: auto;
}

.analysis-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  height: 100%;
}

.analysis-card {
  position: relative;
  padding: 14px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: hidden;
  cursor: pointer;
  transition: all 0.2s ease;
}

.analysis-card:hover {
  border-color: var(--accent-color);
  transform: translateY(-2px);
}

.card-glow {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 3px;
}

.analysis-card.timing .card-glow {
  background: linear-gradient(90deg, #3b82f6 0%, #06b6d4 100%);
}

.analysis-card.power .card-glow {
  background: linear-gradient(90deg, #f59e0b 0%, #ef4444 100%);
}

.analysis-card.area .card-glow {
  background: linear-gradient(90deg, #10b981 0%, #06b6d4 100%);
}

.analysis-card.drc .card-glow {
  background: linear-gradient(90deg, #8b5cf6 0%, #ec4899 100%);
}

.analysis-card.congestion .card-glow {
  background: linear-gradient(90deg, #ef4444 0%, #f59e0b 100%);
}

.analysis-card.wirelength .card-glow {
  background: linear-gradient(90deg, #06b6d4 0%, #3b82f6 100%);
}

.card-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
}

.analysis-card.timing .card-icon {
  background: rgba(59, 130, 246, 0.15);
  color: #3b82f6;
}

.analysis-card.power .card-icon {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}

.analysis-card.area .card-icon {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.analysis-card.drc .card-icon {
  background: rgba(139, 92, 246, 0.15);
  color: #8b5cf6;
}

.analysis-card.congestion .card-icon {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.analysis-card.wirelength .card-icon {
  background: rgba(6, 182, 212, 0.15);
  color: #06b6d4;
}

.card-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.card-label {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.card-value {
  font-size: 20px;
  font-weight: 800;
  color: var(--text-primary);
}

.card-unit {
  font-size: 9px;
  color: var(--text-secondary);
  opacity: 0.7;
}

/* ==================== Metrics Section ==================== */
.metrics-content {
  flex: 1;
  padding: 10px;
  overflow: auto;
}

.metrics-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  height: 100%;
}

.metric-item {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  transition: all 0.15s ease;
  cursor: pointer;
  min-height: 0;
}

.metric-item:hover {
  border-color: var(--accent-color);
}

.metric-indicator {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.metric-indicator.memory {
  background: #8b5cf6;
}

.metric-indicator.core {
  background: #3b82f6;
}

.metric-indicator.cells {
  background: #10b981;
}

.metric-indicator.nets {
  background: #f59e0b;
}

.metric-indicator.timing {
  background: #ef4444;
}

.metric-indicator.wire {
  background: #06b6d4;
}

.metric-label {
  flex: 1;
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.metric-value {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
  font-family: 'JetBrains Mono', monospace;
  flex-shrink: 0;
}

.metric-chart {
  width: 60px;
  flex-shrink: 0;
}

.chart-placeholder {
  height: 20px;
  background: linear-gradient(90deg, var(--border-color) 0%, transparent 100%);
  border-radius: 3px;
  opacity: 0.5;
}

/* ==================== Checklist Section ==================== */
.checklist-content {
  flex: 1;
  padding: 12px;
  overflow: auto;
}

.checklist-placeholder {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  border: 2px dashed var(--border-color);
  border-radius: 10px;
  background: var(--bg-primary);
}

.checklist-placeholder i {
  font-size: 32px;
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

/* ==================== 响应式 ==================== */
@media (max-width: 1200px) {
  .info-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .analysis-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 900px) {
  .main-content {
    flex-direction: column;
  }

  .left-panel,
  .right-panel {
    flex: none;
    height: auto;
  }

  .chip-info-section,
  .layout-section,
  .analysis-section,
  .metrics-section,
  .checklist-section {
    flex: none;
    min-height: 200px;
  }
}
</style>

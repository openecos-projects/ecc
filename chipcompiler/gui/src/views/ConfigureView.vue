<script setup lang="ts">
import { reactive, computed } from 'vue'
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import Checkbox from 'primevue/checkbox'
import Select from 'primevue/select'

// 响应式配置参数
const config = reactive({
  design: "gcd",
  topModule: "gcd",
  die: { boundingBox: "" },
  core: {
    boundingBox: "",
    utilization: 0.39,
    margin: [10, 10],
    aspectRatio: 1
  },
  maxFanout: 20,
  targetDensity: 0.3,
  targetOverflow: 0.1,
  clock: "clk",
  frequencyMax: 100,
  bottomLayer: "MET1",
  topLayer: "MET5",
  floorplan: {
    tapDistance: 58,
    autoPlacePin: { layer: "MET3", width: 300, height: 600 },
    tracks: [
      { layer: "MET1", xStart: 0, xStep: 200, yStart: 0, yStep: 200 },
      { layer: "MET2", xStart: 0, xStep: 200, yStart: 0, yStep: 200 },
      { layer: "MET3", xStart: 0, xStep: 200, yStart: 0, yStep: 200 },
      { layer: "MET4", xStart: 0, xStep: 200, yStart: 0, yStep: 200 },
      { layer: "MET5", xStart: 0, xStep: 200, yStart: 0, yStep: 200 }
    ]
  },
  pdn: {
    io: [
      { netName: "VDD", direction: "INOUT", isPower: true },
      { netName: "VDDIO", direction: "INOUT", isPower: true },
      { netName: "VSS", direction: "INOUT", isPower: false },
      { netName: "VSSIO", direction: "INOUT", isPower: false }
    ],
    globalConnect: [
      { netName: "VDD", instancePinName: "VDD", isPower: true },
      { netName: "VDD", instancePinName: "VDD1", isPower: true },
      { netName: "VDD", instancePinName: "VNW", isPower: true },
      { netName: "VDDIO", instancePinName: "VDDIO", isPower: true },
      { netName: "VSS", instancePinName: "VSS", isPower: false },
      { netName: "VSS", instancePinName: "VSS1", isPower: false },
      { netName: "VSS", instancePinName: "VPW", isPower: false },
      { netName: "VSSIO", instancePinName: "VSSIO", isPower: false }
    ],
    grid: { layer: "MET1", powerNet: "VDD", groundNet: "VSS", width: 0.16, offset: 0 },
    stripe: [
      { layer: "MET4", powerNet: "VDD", groundNet: "VSS", width: 1, pitch: 16, offset: 0.5 },
      { layer: "MET5", powerNet: "VDD", groundNet: "VSS", width: 1, pitch: 16, offset: 0.5 }
    ],
    connectLayers: [
      { layers: ["MET1", "MET5"] },
      { layers: ["MET4", "MET5"] }
    ]
  }
})

const layerOptions = [
  { label: 'MET1', value: 'MET1' },
  { label: 'MET2', value: 'MET2' },
  { label: 'MET3', value: 'MET3' },
  { label: 'MET4', value: 'MET4' },
  { label: 'MET5', value: 'MET5' }
]

const directionOptions = [
  { label: 'INOUT', value: 'INOUT' },
  { label: 'INPUT', value: 'INPUT' },
  { label: 'OUTPUT', value: 'OUTPUT' }
]

const utilizationPercent = computed(() => Math.round(config.core.utilization * 100))
const densityPercent = computed(() => Math.round(config.targetDensity * 100))
const overflowPercent = computed(() => Math.round(config.targetOverflow * 100))

const layersList = ['MET1', 'MET2', 'MET3', 'MET4', 'MET5']
const isLayerInRange = (layer: string): boolean => {
  const bottomIndex = layersList.indexOf(config.bottomLayer)
  const topIndex = layersList.indexOf(config.topLayer)
  const currentIndex = layersList.indexOf(layer)
  return currentIndex >= bottomIndex && currentIndex <= topIndex
}

// CRUD
const addTrack = () => config.floorplan.tracks.push({ layer: "MET1", xStart: 0, xStep: 200, yStart: 0, yStep: 200 })
const removeTrack = (i: number) => config.floorplan.tracks.splice(i, 1)
const addPdnIO = () => config.pdn.io.push({ netName: "", direction: "INOUT", isPower: true })
const removePdnIO = (i: number) => config.pdn.io.splice(i, 1)
const addGlobalConnect = () => config.pdn.globalConnect.push({ netName: "", instancePinName: "", isPower: true })
const removeGlobalConnect = (i: number) => config.pdn.globalConnect.splice(i, 1)
const addStripe = () => config.pdn.stripe.push({ layer: "MET1", powerNet: "VDD", groundNet: "VSS", width: 1, pitch: 16, offset: 0.5 })
const removeStripe = (i: number) => config.pdn.stripe.splice(i, 1)
const addConnectLayer = () => config.pdn.connectLayers.push({ layers: ["MET1", "MET2"] })
const removeConnectLayer = (i: number) => config.pdn.connectLayers.splice(i, 1)

const saveConfig = () => console.log('Saved:', JSON.stringify(config, null, 2))
const resetConfig = () => console.log('Reset')

// 展开/折叠状态
const expandedSections = reactive({
  tracks: true,
  pdnIo: true,
  globalConnect: true,
  stripe: true,
  connectLayers: true
})

const toggleSection = (key: keyof typeof expandedSections) => {
  expandedSections[key] = !expandedSections[key]
}
</script>

<template>
  <div class="config-view">
    <!-- 顶栏 -->
    <header class="topbar">
      <div class="topbar-left">
        <i class="ri-cpu-line"></i>
        <span class="title">{{ config.design }}</span>
        <span class="divider">/</span>
        <span class="subtitle">Configuration</span>
      </div>
      <div class="topbar-right">
        <button class="btn-text" @click="resetConfig">
          <i class="ri-refresh-line"></i>
          Reset
        </button>
        <button class="btn-primary" @click="saveConfig">
          <i class="ri-save-line"></i>
          Save
        </button>
      </div>
    </header>

    <!-- Grid 布局内容 -->
    <main class="content-container">
      <div class="content-grid">
        <!-- 第一行：基础配置 -->
        <section class="card">
          <div class="card-head">
            <i class="ri-cpu-line c-indigo"></i>
            <span>Design</span>
          </div>
          <div class="card-body">
            <div class="field">
              <label>Name</label>
              <InputText v-model="config.design" size="small" />
            </div>
            <div class="field">
              <label>Top Module</label>
              <InputText v-model="config.topModule" size="small" />
            </div>
            <div class="field-row">
              <div class="field">
                <label>Clock</label>
                <InputText v-model="config.clock" size="small" />
              </div>
              <div class="field">
                <label>Freq (MHz)</label>
                <InputNumber v-model="config.frequencyMax" size="small" />
              </div>
            </div>
          </div>
        </section>

        <section class="card">
          <div class="card-head">
            <i class="ri-artboard-2-line c-purple"></i>
            <span>Die</span>
          </div>
          <div class="card-body">
            <div class="field">
              <label>Bounding Box</label>
              <InputText v-model="config.die.boundingBox" size="small" placeholder="x1 y1 x2 y2" />
            </div>
          </div>
        </section>

        <section class="card">
          <div class="card-head">
            <i class="ri-shield-check-line c-orange"></i>
            <span>Constraints</span>
          </div>
          <div class="card-body">
            <div class="field">
              <label>Max Fanout</label>
              <InputNumber v-model="config.maxFanout" size="small" :min="1" />
            </div>
            <div class="field">
              <div class="label-row">
                <label>Target Density</label>
                <span class="tag green">{{ densityPercent }}%</span>
              </div>
              <input type="range" v-model.number="config.targetDensity" min="0" max="1" step="0.01" class="green" />
            </div>
            <div class="field">
              <div class="label-row">
                <label>Target Overflow</label>
                <span class="tag orange">{{ overflowPercent }}%</span>
              </div>
              <input type="range" v-model.number="config.targetOverflow" min="0" max="1" step="0.01" class="orange" />
            </div>
          </div>
        </section>

        <section class="card">
          <div class="card-head">
            <i class="ri-settings-3-line c-cyan"></i>
            <span>Floorplan</span>
          </div>
          <div class="card-body">
            <div class="field-row">
              <div class="field">
                <label>Tap Distance</label>
                <InputNumber v-model="config.floorplan.tapDistance" size="small" suffix=" μm" />
              </div>
              <div class="field">
                <label>Pin Layer</label>
                <Select v-model="config.floorplan.autoPlacePin.layer" :options="layerOptions" optionLabel="label"
                  optionValue="value" size="small" />
              </div>
            </div>
            <div class="field-row">
              <div class="field">
                <label>Pin Width</label>
                <InputNumber v-model="config.floorplan.autoPlacePin.width" size="small" suffix=" nm" />
              </div>
              <div class="field">
                <label>Pin Height</label>
                <InputNumber v-model="config.floorplan.autoPlacePin.height" size="small" suffix=" nm" />
              </div>
            </div>
          </div>
        </section>

        <!-- 第二行 -->
        <section class="card">
          <div class="card-head">
            <i class="ri-box-3-line c-green"></i>
            <span>Core</span>
          </div>
          <div class="card-body">
            <div class="field">
              <label>Bounding Box</label>
              <InputText v-model="config.core.boundingBox" size="small" placeholder="x1 y1 x2 y2" />
            </div>
            <div class="field">
              <div class="label-row">
                <label>Utilization</label>
                <span class="tag blue">{{ utilizationPercent }}%</span>
              </div>
              <input type="range" v-model.number="config.core.utilization" min="0" max="1" step="0.01" />
            </div>
            <div class="field-row">
              <div class="field">
                <label>Aspect Ratio</label>
                <InputNumber v-model="config.core.aspectRatio" size="small" :min="0.1" :step="0.1" />
              </div>
              <div class="field">
                <label>Margin X</label>
                <InputNumber v-model="config.core.margin[0]" size="small" suffix=" μm" />
              </div>
              <div class="field">
                <label>Margin Y</label>
                <InputNumber v-model="config.core.margin[1]" size="small" suffix=" μm" />
              </div>
            </div>
          </div>
        </section>

        <section class="card">
          <div class="card-head">
            <i class="ri-stack-line c-cyan"></i>
            <span>Routing Layers</span>
          </div>
          <div class="card-body">
            <div class="layer-list">
              <div v-for="l in layerOptions" :key="l.value" class="layer-item"
                :class="{ active: isLayerInRange(l.value) }">
                {{ l.label }}
              </div>
            </div>
            <div class="field-row" style="margin-top: 12px;">
              <div class="field">
                <label>Bottom</label>
                <Select v-model="config.bottomLayer" :options="layerOptions" optionLabel="label" optionValue="value"
                  size="small" />
              </div>
              <div class="field">
                <label>Top</label>
                <Select v-model="config.topLayer" :options="layerOptions" optionLabel="label" optionValue="value"
                  size="small" />
              </div>
            </div>
          </div>
        </section>

        <section class="card">
          <div class="card-head">
            <i class="ri-flashlight-line c-yellow"></i>
            <span>PDN Grid</span>
          </div>
          <div class="card-body">
            <div class="field-row">
              <div class="field">
                <label>Layer</label>
                <Select v-model="config.pdn.grid.layer" :options="layerOptions" optionLabel="label" optionValue="value"
                  size="small" />
              </div>
              <div class="field">
                <label>Width (μm)</label>
                <InputNumber v-model="config.pdn.grid.width" size="small" :minFractionDigits="2" />
              </div>
            </div>
            <div class="field-row">
              <div class="field">
                <label>Power Net</label>
                <InputText v-model="config.pdn.grid.powerNet" size="small" />
              </div>
              <div class="field">
                <label>Ground Net</label>
                <InputText v-model="config.pdn.grid.groundNet" size="small" />
              </div>
            </div>
          </div>
        </section>

        <section class="card">
          <div class="card-head clickable" @click="toggleSection('connectLayers')">
            <i class="ri-stack-line c-yellow"></i>
            <span>Layer Connections</span>
            <span class="count">{{ config.pdn.connectLayers.length }}</span>
            <i :class="expandedSections.connectLayers ? 'ri-arrow-up-s-line' : 'ri-arrow-down-s-line'"
              class="toggle"></i>
          </div>
          <div v-show="expandedSections.connectLayers" class="card-body compact">
            <div class="connect-list">
              <div v-for="(c, i) in config.pdn.connectLayers" :key="i" class="connect-row">
                <Select v-model="c.layers[0]" :options="layerOptions" optionLabel="label" optionValue="value"
                  size="small" />
                <i class="ri-arrow-left-right-line"></i>
                <Select v-model="c.layers[1]" :options="layerOptions" optionLabel="label" optionValue="value"
                  size="small" />
                <button class="btn-icon danger" @click="removeConnectLayer(i)">
                  <i class="ri-delete-bin-line"></i>
                </button>
              </div>
            </div>
            <button class="btn-add" @click="addConnectLayer"><i class="ri-add-line"></i> Add</button>
          </div>
        </section>

        <!-- 第三行：PDN IO 和 Global Connect -->
        <section class="card">
          <div class="card-head clickable" @click="toggleSection('pdnIo')">
            <i class="ri-plug-line c-yellow"></i>
            <span>PDN IO</span>
            <span class="count">{{ config.pdn.io.length }}</span>
            <i :class="expandedSections.pdnIo ? 'ri-arrow-up-s-line' : 'ri-arrow-down-s-line'" class="toggle"></i>
          </div>
          <div v-show="expandedSections.pdnIo" class="card-body compact">
            <table class="mini-table">
              <thead>
                <tr>
                  <th>Net</th>
                  <th>Direction</th>
                  <th>Power</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(io, i) in config.pdn.io" :key="i">
                  <td>
                    <InputText v-model="io.netName" size="small" />
                  </td>
                  <td><Select v-model="io.direction" :options="directionOptions" optionLabel="label" optionValue="value"
                      size="small" /></td>
                  <td class="center">
                    <Checkbox v-model="io.isPower" :binary="true" />
                  </td>
                  <td><button class="btn-icon danger" @click="removePdnIO(i)"><i
                        class="ri-delete-bin-line"></i></button></td>
                </tr>
              </tbody>
            </table>
            <button class="btn-add" @click="addPdnIO"><i class="ri-add-line"></i> Add</button>
          </div>
        </section>

        <section class="card span-2">
          <div class="card-head clickable" @click="toggleSection('globalConnect')">
            <i class="ri-links-line c-yellow"></i>
            <span>Global Connect</span>
            <span class="count">{{ config.pdn.globalConnect.length }}</span>
            <i :class="expandedSections.globalConnect ? 'ri-arrow-up-s-line' : 'ri-arrow-down-s-line'"
              class="toggle"></i>
          </div>
          <div v-show="expandedSections.globalConnect" class="card-body compact">
            <table class="mini-table">
              <thead>
                <tr>
                  <th>Net</th>
                  <th>Instance Pin</th>
                  <th>Power</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(gc, i) in config.pdn.globalConnect" :key="i">
                  <td>
                    <InputText v-model="gc.netName" size="small" />
                  </td>
                  <td>
                    <InputText v-model="gc.instancePinName" size="small" />
                  </td>
                  <td class="center">
                    <Checkbox v-model="gc.isPower" :binary="true" />
                  </td>
                  <td><button class="btn-icon danger" @click="removeGlobalConnect(i)"><i
                        class="ri-delete-bin-line"></i></button></td>
                </tr>
              </tbody>
            </table>
            <button class="btn-add" @click="addGlobalConnect"><i class="ri-add-line"></i> Add</button>
          </div>
        </section>

        <!-- 最后：Tracks 和 PDN Stripe（全宽） -->
        <section class="card full-width">
          <div class="card-head clickable" @click="toggleSection('tracks')">
            <i class="ri-grid-line c-cyan"></i>
            <span>Tracks</span>
            <span class="count">{{ config.floorplan.tracks.length }}</span>
            <i :class="expandedSections.tracks ? 'ri-arrow-up-s-line' : 'ri-arrow-down-s-line'" class="toggle"></i>
          </div>
          <div v-show="expandedSections.tracks" class="card-body compact">
            <table class="mini-table table-fixed">
              <thead>
                <tr>
                  <th>Layer</th>
                  <th>X Start</th>
                  <th>X Step</th>
                  <th>Y Start</th>
                  <th>Y Step</th>
                  <th class="col-action"></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(t, i) in config.floorplan.tracks" :key="i">
                  <td><Select v-model="t.layer" :options="layerOptions" optionLabel="label" optionValue="value"
                      size="small" /></td>
                  <td>
                    <InputNumber v-model="t.xStart" size="small" />
                  </td>
                  <td>
                    <InputNumber v-model="t.xStep" size="small" />
                  </td>
                  <td>
                    <InputNumber v-model="t.yStart" size="small" />
                  </td>
                  <td>
                    <InputNumber v-model="t.yStep" size="small" />
                  </td>
                  <td class="col-action"><button class="btn-icon danger" @click="removeTrack(i)"><i
                        class="ri-delete-bin-line"></i></button></td>
                </tr>
              </tbody>
            </table>
            <button class="btn-add" @click="addTrack"><i class="ri-add-line"></i> Add</button>
          </div>
        </section>

        <section class="card full-width">
          <div class="card-head clickable" @click="toggleSection('stripe')">
            <i class="ri-layout-column-line c-yellow"></i>
            <span>PDN Stripe</span>
            <span class="count">{{ config.pdn.stripe.length }}</span>
            <i :class="expandedSections.stripe ? 'ri-arrow-up-s-line' : 'ri-arrow-down-s-line'" class="toggle"></i>
          </div>
          <div v-show="expandedSections.stripe" class="card-body compact">
            <table class="mini-table table-fixed">
              <thead>
                <tr>
                  <th>Layer</th>
                  <th>Power Net</th>
                  <th>Ground Net</th>
                  <th>Width</th>
                  <th>Pitch</th>
                  <th>Offset</th>
                  <th class="col-action"></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(s, i) in config.pdn.stripe" :key="i">
                  <td><Select v-model="s.layer" :options="layerOptions" optionLabel="label" optionValue="value"
                      size="small" /></td>
                  <td>
                    <InputText v-model="s.powerNet" size="small" />
                  </td>
                  <td>
                    <InputText v-model="s.groundNet" size="small" />
                  </td>
                  <td>
                    <InputNumber v-model="s.width" size="small" :minFractionDigits="1" />
                  </td>
                  <td>
                    <InputNumber v-model="s.pitch" size="small" />
                  </td>
                  <td>
                    <InputNumber v-model="s.offset" size="small" :minFractionDigits="1" />
                  </td>
                  <td class="col-action"><button class="btn-icon danger" @click="removeStripe(i)"><i
                        class="ri-delete-bin-line"></i></button></td>
                </tr>
              </tbody>
            </table>
            <button class="btn-add" @click="addStripe"><i class="ri-add-line"></i> Add</button>
          </div>
        </section>
      </div>
    </main>
  </div>
</template>

<style scoped>
.config-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
  color: var(--text-primary);
}

/* 顶栏 */
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
  flex-shrink: 0;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.topbar-left i {
  font-size: 18px;
  color: #6366f1;
}

.topbar-left .title {
  font-weight: 600;
  font-family: 'Fira Code', monospace;
}

.topbar-left .divider {
  color: var(--text-secondary);
}

.topbar-left .subtitle {
  color: var(--text-secondary);
}

.topbar-right {
  display: flex;
  gap: 8px;
}

.btn-text {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  border-radius: 6px;
  transition: all 0.15s;
}

.btn-text:hover {
  background: var(--bg-primary);
  color: var(--text-primary);
}

.btn-primary {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 14px;
  border: none;
  background: #6366f1;
  color: white;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  border-radius: 6px;
  transition: all 0.15s;
}

.btn-primary:hover {
  background: #4f46e5;
}

/* Grid 布局容器 */
.content-container {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.content-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  max-width: 1600px;
  margin: 0 auto;
}

/* 卡片 */
.card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
}

.card.span-2 {
  grid-column: span 2;
}

.card.full-width {
  grid-column: 1 / -1;
}

.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-color);
  font-size: 12px;
  font-weight: 600;
}

.card-head.clickable {
  cursor: pointer;
  transition: background 0.15s;
}

.card-head.clickable:hover {
  background: var(--bg-primary);
}

.card-head i:first-child {
  font-size: 14px;
}

.card-head .count {
  margin-left: auto;
  padding: 2px 6px;
  background: var(--bg-primary);
  border-radius: 4px;
  font-size: 10px;
  color: var(--text-secondary);
}

.card-head .toggle {
  color: var(--text-secondary);
  font-size: 16px;
}

.card-body {
  padding: 12px;
}

.card-body.compact {
  padding: 8px;
}

/* 颜色类 */
.c-indigo {
  color: #6366f1;
}

.c-purple {
  color: #8b5cf6;
}

.c-green {
  color: #10b981;
}

.c-orange {
  color: #f59e0b;
}

.c-cyan {
  color: #06b6d4;
}

.c-yellow {
  color: #eab308;
}

/* 表单 */
.field {
  margin-bottom: 10px;
}

.field:last-child {
  margin-bottom: 0;
}

.field label {
  display: block;
  font-size: 10px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.label-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.label-row label {
  margin-bottom: 0;
}

.field-row {
  display: flex;
  gap: 10px;
}

.field-row .field {
  flex: 1;
  min-width: 0;
}

/* Tag */
.tag {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Fira Code', monospace;
}

.tag.blue {
  background: rgba(99, 102, 241, 0.15);
  color: #6366f1;
}

.tag.green {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.tag.orange {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}

/* Range Slider */
input[type="range"] {
  width: 100%;
  height: 4px;
  -webkit-appearance: none;
  appearance: none;
  background: var(--border-color);
  border-radius: 2px;
  outline: none;
}

input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #6366f1;
  cursor: pointer;
}

input[type="range"].green::-webkit-slider-thumb {
  background: #10b981;
}

input[type="range"].orange::-webkit-slider-thumb {
  background: #f59e0b;
}

/* Layer List */
.layer-list {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.layer-item {
  padding: 4px 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-size: 11px;
  font-family: 'Fira Code', monospace;
  color: var(--text-secondary);
  transition: all 0.15s;
}

.layer-item.active {
  background: rgba(6, 182, 212, 0.1);
  border-color: #06b6d4;
  color: #06b6d4;
}

/* Mini Table */
.mini-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}

.mini-table.table-fixed {
  table-layout: fixed;
}

.mini-table.table-fixed th,
.mini-table.table-fixed td {
  width: 16%;
}

.mini-table.table-fixed th.col-action,
.mini-table.table-fixed td.col-action {
  width: 4%;
  text-align: center;
}

.mini-table th {
  text-align: left;
  padding: 6px 4px;
  font-size: 10px;
  font-weight: 500;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.3px;
  border-bottom: 1px solid var(--border-color);
}

.mini-table td {
  padding: 4px;
  vertical-align: middle;
}

.mini-table td.center {
  text-align: center;
}

.mini-table :deep(.p-inputtext),
.mini-table :deep(.p-inputnumber),
.mini-table :deep(.p-select) {
  width: 100%;
}

/* Buttons */
.btn-icon {
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: 4px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}

.btn-icon.danger:hover {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.btn-add {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  width: 100%;
  padding: 6px;
  margin-top: 8px;
  border: 1px dashed var(--border-color);
  background: transparent;
  color: var(--text-secondary);
  font-size: 11px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-add:hover {
  border-color: #6366f1;
  color: #6366f1;
  background: rgba(99, 102, 241, 0.05);
}

/* Connect List */
.connect-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.connect-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  background: var(--bg-primary);
  border-radius: 4px;
}

.connect-row :deep(.p-select) {
  flex: 1;
}

.connect-row>i {
  color: var(--text-secondary);
  font-size: 12px;
}

/* Input overrides */
:deep(.p-inputtext),
:deep(.p-inputnumber-input),
:deep(.p-select) {
  background: var(--bg-primary);
  border-color: var(--border-color);
  font-size: 12px;
}

.field :deep(.p-inputtext),
.field :deep(.p-inputnumber),
.field :deep(.p-select) {
  width: 100%;
}

:deep(.p-inputtext:focus),
:deep(.p-inputnumber-input:focus) {
  border-color: #6366f1;
  box-shadow: none;
}

/* Responsive */
@media (max-width: 1400px) {
  .content-grid {
    grid-template-columns: repeat(3, 1fr);
  }

  .card.span-2 {
    grid-column: span 2;
  }
}

@media (max-width: 1024px) {
  .content-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .card.span-2 {
    grid-column: span 2;
  }
}

@media (max-width: 768px) {
  .content-grid {
    grid-template-columns: 1fr;
  }

  .card.span-2,
  .card.full-width {
    grid-column: span 1;
  }

  .topbar {
    flex-direction: column;
    gap: 10px;
    align-items: flex-start;
  }

  .topbar-right {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>

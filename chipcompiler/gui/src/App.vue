<template>
  <div class="app-container">
    <router-view />
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useThemeStore } from '@/stores/themeStore'
const themeStore = useThemeStore()

onMounted(() => {
  themeStore.initTheme()
})
</script>

<style scoped>
.app-container {
  width: 100%;
  height: 100%;
  max-width: 100vw;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
</style>

<template>
  <div class="w-full h-full flex flex-col items-center justify-center">
    <button @click="handleRunRTL2GDS" class="bg-blue-500 text-white px-4 py-2 rounded-md">Run RTL2GDS</button>
    <button @click="handleGetInfo(StepEnum.synthesis, InfoEnum.views)"
      class="bg-green-500 text-white px-4 py-2 rounded-md mt-2">Get Info - synthesis
      views</button>
    <button @click="handleGetInfo(StepEnum.cts, InfoEnum.subflow)"
      class="bg-green-500 text-white px-4 py-2 rounded-md mt-2">Get Info - CTS
      subflow</button>

  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { rtl2gdsApi, getInfoApi } from '@/api/flow';
import { CMDEnum, StepEnum, InfoEnum } from '@/api/type';

const isLoading = ref(false);

const handleRunRTL2GDS = async () => {
  if (isLoading.value) return;
  isLoading.value = true;
  try {
    const response = await rtl2gdsApi({
      cmd: CMDEnum.rtl2gds,
      data: { rerun: true }
    });
    console.log(response);
  } catch (error) {
    console.error(error);
  } finally {
    isLoading.value = false;
  }
}


const handleGetInfo = async (step: StepEnum, id: InfoEnum) => {
  console.log(step, id);
  if (isLoading.value) return;
  isLoading.value = true;
  try {
    const request = {
      cmd: CMDEnum.get_info,
      data: { step: step, id: id }
    }
    console.log(request);
    const response = await getInfoApi(request);
    console.log(response);
  } catch (error) {
    console.error(error);
  } finally {
    isLoading.value = false;
  }
}
</script>

<style scoped></style>
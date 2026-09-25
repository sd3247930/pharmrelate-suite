<script setup lang="ts">
import { RouterLink } from 'vue-router';

import AppButton from '../components/AppButton.vue';
import AppCard from '../components/AppCard.vue';
</script>

<template>
  <AppCard title="页面不存在" subtitle="该路径没有对应的功能页面。">
    <p class="hint">请从左侧导航选择功能，或返回工作台。</p>
    <template #footer>
      <RouterLink to="/">
        <AppButton variant="primary">返回工作台</AppButton>
      </RouterLink>
    </template>
  </AppCard>
</template>

<style scoped>
.hint {
  color: var(--color-text-muted);
}
</style>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';

import AppSidebar from './components/AppSidebar.vue';
import AppTopBar from './components/AppTopBar.vue';
import { useSystemStore } from './stores/system';

/**
 * 应用外壳：左侧主导航 + 顶部状态栏 + 内容工作区。
 *
 * 顶部状态栏长期可见，保证"现在发生了什么"永远在视野内；
 * 关键状态不藏在二级页面里。
 */
const collapsed = ref(false);
const route = useRoute();
const system = useSystemStore();

onMounted(() => {
  void system.checkHealthWithRetry();
});
</script>

<template>
  <div class="app-shell">
    <AppSidebar :collapsed="collapsed" @toggle="collapsed = !collapsed" />
    <div class="app-shell__main">
      <AppTopBar />
      <main class="app-shell__content" tabindex="-1">
        <h1 class="app-shell__title">{{ (route.meta.title as string) || '工作台' }}</h1>
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  height: 100%;
  overflow: hidden;
}

.app-shell__main {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}

.app-shell__content {
  flex: 1;
  padding: var(--space-5);
  overflow-y: auto;
}

.app-shell__title {
  margin-bottom: var(--space-5);
  font-size: var(--text-2xl);
}
</style>

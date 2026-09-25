<script setup lang="ts">
import { RefreshCw, UserRound, WifiOff } from 'lucide-vue-next';
import { computed } from 'vue';

import AppButton from './AppButton.vue';
import AppStatusBadge from './AppStatusBadge.vue';
import { useBatchStore } from '../stores/batch';
import { useSystemStore } from '../stores/system';

/**
 * 顶部状态栏 —— 长期可见的"现在到底发生了什么"。
 *
 * 阶段 1 显示：当前批次 / 批次状态 / 本地服务 / 基准一致性 / 操作人。
 * 二期会在同一位置补上局域网设备数、云端连接、同步队列条数。
 */
const system = useSystemStore();
const batch = useBatchStore();

const batchNoText = computed(() => batch.batchNo.trim() || '未创建');

const serviceTone = computed(() => {
  switch (system.serviceState) {
    case 'online':
      return { tone: 'verified' as const, label: '本地服务' };
    case 'connecting':
      return { tone: 'collecting' as const, label: '本地服务' };
    case 'offline':
      return { tone: 'offline' as const, label: '本地服务' };
    default:
      return { tone: 'draft' as const, label: '本地服务' };
  }
});

const serviceDetail = computed(() => {
  if (system.serviceState === 'online') return system.version ? `v${system.version}` : '已连接';
  if (system.serviceState === 'connecting') return '连接中';
  if (system.serviceState === 'offline') return '未连接';
  return '未检测';
});
</script>

<template>
  <header class="app-topbar">
    <div class="app-topbar__field">
      <span class="app-topbar__key">当前批次</span>
      <span class="app-topbar__value code-text">{{ batchNoText }}</span>
    </div>

    <div class="app-topbar__field">
      <span class="app-topbar__key">批次状态</span>
      <AppStatusBadge
        :tone="(batch.status as never)"
        :label="batch.statusLabel"
        :detail="batch.editable ? undefined : '只读'"
      />
    </div>

    <div class="app-topbar__field">
      <span class="app-topbar__key">本地服务</span>
      <AppStatusBadge :tone="serviceTone.tone" :label="serviceTone.label" :detail="serviceDetail" />
    </div>

    <div class="app-topbar__field">
      <span class="app-topbar__key">黄金基准</span>
      <AppStatusBadge
        :tone="system.goldenOk ? 'verified' : 'void'"
        :label="system.goldenOk ? '字节级一致' : '基准异常'"
        :detail="system.golden.length ? `${system.golden.length} 个文件` : undefined"
      />
    </div>

    <div class="app-topbar__spacer" />

    <AppButton variant="ghost" :loading="system.serviceState === 'connecting'" @click="system.checkHealth()">
      <template #icon>
        <RefreshCw v-if="system.serviceState !== 'offline'" :size="16" aria-hidden="true" />
        <WifiOff v-else :size="16" aria-hidden="true" />
      </template>
      重新检测
    </AppButton>

    <div class="app-topbar__field">
      <UserRound :size="16" aria-hidden="true" />
      <span class="app-topbar__value">操作员</span>
    </div>

  </header>
</template>

<style scoped>
.app-topbar {
  display: flex;
  align-items: center;
  gap: var(--space-5);
  height: var(--topbar-height);
  padding: 0 var(--space-5);
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
}

.app-topbar__field {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  white-space: nowrap;
}

.app-topbar__key {
  color: var(--color-text-subtle);
}

.app-topbar__value {
  font-weight: var(--weight-medium);
}

.app-topbar__spacer {
  flex: 1;
}
</style>

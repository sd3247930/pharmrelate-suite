/**
 * 系统状态：本地服务连接、黄金基准一致性。
 *
 * 阶段 1 的"顶部状态栏"就靠这里的数据驱动。二期接入局域网/云端后，
 * 这里再扩展 lan / cloud / sync 三组状态，渲染层不用重写。
 */

import { defineStore } from 'pinia';
import { computed, ref } from 'vue';

import { api } from '../api/client';
import type { GoldenInfo } from '../types/batch';

export type ServiceState = 'unknown' | 'connecting' | 'online' | 'offline';

export const useSystemStore = defineStore('system', () => {
  const serviceState = ref<ServiceState>('unknown');
  const version = ref('');
  const pythonVersion = ref('');
  const golden = ref<GoldenInfo[]>([]);
  const lastError = ref('');
  const lastCheckedAt = ref('');

  const goldenOk = computed(() => golden.value.length > 0 && golden.value.every((item) => item.roundtripOk));
  const isOnline = computed(() => serviceState.value === 'online');

  async function checkHealth(): Promise<void> {
    serviceState.value = serviceState.value === 'online' ? 'online' : 'connecting';
    try {
      const health = await api.health();
      serviceState.value = 'online';
      version.value = health.version;
      pythonVersion.value = health.python;
      golden.value = health.golden;
      lastError.value = '';
    } catch (error) {
      serviceState.value = 'offline';
      lastError.value = error instanceof Error ? error.message : String(error);
    } finally {
      lastCheckedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    }
  }

  /**
   * 启动时带重试的健康检查。
   *
   * 桌面壳拉起 Python 服务需要一两秒，首次请求必然失败；
   * 直接显示"未连接"会让操作员以为系统坏了。
   */
  async function checkHealthWithRetry(attempts = 12, delayMs = 700): Promise<void> {
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      await checkHealth();
      if (serviceState.value === 'online') return;
      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
  }

  return {
    serviceState,
    version,
    pythonVersion,
    golden,
    goldenOk,
    isOnline,
    lastError,
    lastCheckedAt,
    checkHealth,
    checkHealthWithRetry,
  };
});

/**
 * 扫码会话 store。

 * 关键约定：**状态只由后端返回，前端不自行推进**。
 * 这里做三件事：保存后端快照、把操作员动作转成 API 调用、在拦截/报警时触发声音。
 */

import { defineStore } from 'pinia';
import { computed, ref } from 'vue';

import { ApiError, api } from '../api/client';
import { playAlarm, type AlarmTone } from '../services/alarm';
import type { EditHistory, ScanEvent, ScanSnapshot, SlotEditResponse } from '../types/batch';

/** 事件码 → 声音。成功音轻、异常音重，与 V1.1 56 章的音型约定一致。 */
function toneFor(event: ScanEvent | null): AlarmTone | null {
  if (!event) return null;
  if (!event.blocking) return 'scan-success';
  switch (event.code) {
    case 'NO_CODE':
      return null; // 空帧在连续取流里是常态，不值得响
    case 'MULTI_CODE':
    case 'CONFLICT':
    case 'DUPLICATE_CODE':
    case 'WRONG_LAYER':
    case 'OVERFLOW':
      return 'scan-error';
    default:
      return 'scan-warning';
  }
}

export const useScanStore = defineStore('scan', () => {
  const snapshot = ref<ScanSnapshot | null>(null);
  const busy = ref(false);
  const errorMessage = ref('');
  /** 被拦截的最近一次事件，界面用它显示恢复路径。 */
  const blocked = ref<ScanEvent | null>(null);
  const cameraRunning = ref(false);
  const cameraError = ref('');
  const cameraHint = ref('');
  const frameTick = ref(0);
  const history = ref<EditHistory>({
    canUndo: 0,
    canRedo: 0,
    undoLabel: '',
    redoLabel: '',
    maxSteps: 50,
  });

  const status = computed(() => snapshot.value?.status ?? 'idle');
  const statusLabel = computed(() => snapshot.value?.statusLabel ?? '待开始');
  const currentCan = computed(() => snapshot.value?.currentCanIndex ?? 1);
  const plannedCanCount = computed(() => snapshot.value?.plannedCanCount ?? 0);
  const currentCanPlanned = computed(() => snapshot.value?.currentCanPlanned ?? 0);
  const currentCanScanned = computed(() => snapshot.value?.currentCanScanned ?? 0);
  const remainingInCan = computed(() => snapshot.value?.remainingInCan ?? 0);
  const missingParticles = computed(() => snapshot.value?.missingParticles ?? 0);

  const canProgressPercent = computed(() => {
    if (!currentCanPlanned.value) return 0;
    return Math.min(
      100,
      Math.round((currentCanScanned.value / currentCanPlanned.value) * 1000) / 10,
    );
  });

  /** 当前状态要求"单码"还是"多码"——决定界面上提示操作员怎么拍。 */
  const scanMode = computed<'single' | 'batch' | 'none'>(() => {
    switch (status.value) {
      case 'box_scanning':
      case 'can_scanning':
        return 'single';
      case 'particle_scanning':
        return 'batch';
      default:
        return 'none';
    }
  });

  function apply(next: ScanSnapshot): void {
    snapshot.value = next;
    const event = next.lastEvent;
    blocked.value = event && event.blocking ? event : null;
    const tone = toneFor(event);
    if (tone) playAlarm(tone);
  }

  async function run(action: () => Promise<ScanSnapshot>): Promise<boolean> {
    busy.value = true;
    errorMessage.value = '';
    try {
      apply(await action());
      return true;
    } catch (error) {
      if (error instanceof ApiError) {
        // 409 表示"当前状态不允许该操作"：把状态与恢复路径原样呈现
        errorMessage.value = error.message;
        blocked.value = {
          code: String(error.detail.reason ?? error.code),
          label: '操作被拒绝',
          message: error.message,
          blocking: true,
          needsAlarm: false,
          detail: error.detail,
        };
        playAlarm('scan-warning');
      } else {
        errorMessage.value = error instanceof Error ? error.message : String(error);
      }
      return false;
    } finally {
      busy.value = false;
    }
  }

  async function load(batchId: string): Promise<boolean> {
    return run(() => api.scanSession(batchId));
  }

  /**
   * 槽位编辑统一收口。

   * 编辑会改动批次数据，因此每次编辑后都重新拉会话快照，
   * 保证进度、槽位、状态全部来自后端而不是本地推算。
   */
  async function edit(
    batchId: string,
    action: () => Promise<SlotEditResponse>,
  ): Promise<boolean> {
    busy.value = true;
    errorMessage.value = '';
    try {
      const result = await action();
      history.value = result.history;
      await run(() => api.scanSession(batchId));
      return true;
    } catch (error) {
      if (error instanceof ApiError) {
        errorMessage.value = error.message;
        blocked.value = {
          code: String(error.detail.reason ?? error.code),
          label: '编辑被拒绝',
          message: error.message,
          blocking: true,
          needsAlarm: false,
          detail: error.detail,
        };
        playAlarm('scan-warning');
      } else {
        errorMessage.value = error instanceof Error ? error.message : String(error);
      }
      return false;
    } finally {
      busy.value = false;
    }
  }

  const removeSlot = (batchId: string, code: string) =>
    edit(batchId, () => api.slotDelete(batchId, code));

  const replaceSlot = (batchId: string, code: string, newCode: string) =>
    edit(batchId, () => api.slotReplace(batchId, code, newCode));

  const clearCan = (batchId: string, canIndex: number) =>
    edit(batchId, () => api.clearCan(batchId, canIndex));

  const undo = (batchId: string) => edit(batchId, () => api.scanUndo(batchId));

  const redo = (batchId: string) => edit(batchId, () => api.scanRedo(batchId));

  /** 手动输入 / 条码枪 HID / 拍照识别，最终都汇到这一个入口。 */
  async function submitCodes(
    batchId: string,
    codes: string[],
    conflicts: Array<Record<string, unknown>> = [],
  ): Promise<boolean> {
    const cleaned = codes.map((item) => item.trim()).filter(Boolean);
    if (!cleaned.length && !conflicts.length) return false;
    return run(() => api.scanFrame(batchId, cleaned, conflicts));
  }

  async function confirm(batchId: string): Promise<boolean> {
    return run(() => api.scanConfirm(batchId));
  }

  async function rescan(batchId: string): Promise<boolean> {
    return run(() => api.scanRescan(batchId));
  }

  async function nextCan(batchId: string, proceed: boolean): Promise<boolean> {
    return run(() => api.scanNextCan(batchId, proceed));
  }

  async function startCamera(batchId: string, kind: 'opencv' | 'test_image' = 'opencv') {
    busy.value = true;
    cameraError.value = '';
    cameraHint.value = '';
    try {
      const status = await api.cameraStart({
        kind,
        batchId,
        // maxWidth 留 0 → 用后端识别管线的默认 1920
        recognizeIntervalMs: 300,
      });
      cameraRunning.value = status.running;
      cameraError.value = status.error;
      cameraHint.value = status.hint;
      return status.running;
    } catch (error) {
      cameraError.value = error instanceof Error ? error.message : String(error);
      cameraRunning.value = false;
      return false;
    } finally {
      busy.value = false;
    }
  }

  async function stopCamera(): Promise<void> {
    try {
      await api.cameraStop();
    } finally {
      cameraRunning.value = false;
    }
  }

  function reset(): void {
    snapshot.value = null;
    blocked.value = null;
    errorMessage.value = '';
    cameraRunning.value = false;
    cameraError.value = '';
    cameraHint.value = '';
    history.value = {
      canUndo: 0,
      canRedo: 0,
      undoLabel: '',
      redoLabel: '',
      maxSteps: 50,
    };
  }

  return {
    snapshot,
    busy,
    errorMessage,
    blocked,
    cameraRunning,
    cameraError,
    cameraHint,
    frameTick,
    history,
    status,
    statusLabel,
    currentCan,
    plannedCanCount,
    currentCanPlanned,
    currentCanScanned,
    remainingInCan,
    missingParticles,
    canProgressPercent,
    scanMode,
    load,
    submitCodes,
    removeSlot,
    replaceSlot,
    clearCan,
    undo,
    redo,
    confirm,
    rescan,
    nextCan,
    startCamera,
    stopCamera,
    apply,
    reset,
  };
});

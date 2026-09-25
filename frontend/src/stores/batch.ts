/**
 * 批次草稿：界面 1（基础信息）+ 界面 2（包装结构）的数据与校验。
 *
 * 阶段 3 会在同一 store 上追加扫码状态机与槽位数据，因此这里先把
 * "计划 vs 实际"的口径固定下来（plannedParticleCount 与 particles 分开存）。
 */

import { defineStore } from 'pinia';
import { computed, ref } from 'vue';

import { api, ApiError } from '../api/client';
import {
  MAX_CANS,
  MAX_PARTICLES_PER_BATCH,
  MAX_PARTICLES_PER_CAN,
  MIN_CANS,
  type BatchIssue,
  type BatchPayload,
  type CanPayload,
} from '../types/batch';

function todayIso(offsetDays = 0): string {
  const date = new Date();
  date.setDate(date.getDate() + offsetDays);
  return date.toISOString().slice(0, 10);
}

function emptyCan(index: number): CanPayload {
  return { index, code: '', plannedParticleCount: 0, particles: [] };
}

export const useBatchStore = defineStore('batch', () => {
  const batchNo = ref('');
  const madeDate = ref(todayIso());
  const validateDate = ref(todayIso(30));
  const boxCode = ref('');
  const cans = ref<CanPayload[]>([emptyCan(1)]);

  const issues = ref<BatchIssue[]>([]);
  const preview = ref('');
  const previewSha256 = ref('');
  const busy = ref(false);
  const errorMessage = ref('');
  const conflictOptions = ref<Array<{ action: string; label: string }>>([]);

  const canCount = computed(() => cans.value.length);
  const plannedParticleTotal = computed(() =>
    cans.value.reduce((sum, can) => sum + (can.plannedParticleCount || 0), 0),
  );
  const overBatchLimit = computed(() => plannedParticleTotal.value > MAX_PARTICLES_PER_BATCH);
  const progressPercent = computed(() =>
    Math.min(100, Math.round((plannedParticleTotal.value / MAX_PARTICLES_PER_BATCH) * 1000) / 10),
  );

  function setCanCount(count: number): void {
    const clamped = Math.min(MAX_CANS, Math.max(MIN_CANS, Math.trunc(count) || MIN_CANS));
    while (cans.value.length < clamped) cans.value.push(emptyCan(cans.value.length + 1));
    while (cans.value.length > clamped) cans.value.pop();
    cans.value.forEach((can, index) => {
      can.index = index + 1;
    });
  }

  function clampParticles(index: number): void {
    const can = cans.value[index];
    if (!can) return;
    if (can.plannedParticleCount > MAX_PARTICLES_PER_CAN) can.plannedParticleCount = MAX_PARTICLES_PER_CAN;
    if (can.plannedParticleCount < 0) can.plannedParticleCount = 0;
  }

  function toPayload(): BatchPayload {
    return {
      batchNo: batchNo.value.trim(),
      madeDate: madeDate.value,
      validateDate: validateDate.value,
      box: {
        code: boxCode.value.trim(),
        cans: cans.value.map((can) => ({ ...can, particles: [...can.particles] })),
      },
    };
  }

  function loadFromPayload(payload: BatchPayload): void {
    batchNo.value = payload.batchNo;
    madeDate.value = payload.madeDate;
    validateDate.value = payload.validateDate;
    boxCode.value = payload.box.code;
    cans.value = payload.box.cans.map((can) => ({ ...can, particles: [...can.particles] }));
  }

  /**
   * 从真实基准 XML 载入结构。
   *
   * 这里刻意用 DOMParser 解析后端返回的基准文件，而不是在前端硬编码样例数据——
   * 这样"载入样例 → 生成 XML → 与基准比对"是一条真实的数据链路。
   */
  function loadFromGoldenXml(xml: string): void {
    const doc = new DOMParser().parseFromString(xml, 'application/xml');
    const batchElement = doc.querySelector('Batch');
    const boxElement = doc.querySelector('Code[packLayer="3"]');
    if (!batchElement || !boxElement) {
      throw new Error('基准 XML 结构不符合预期，无法载入。');
    }

    const boxValue = boxElement.getAttribute('curCode') ?? '';
    const grouped = new Map<string, string[]>();
    const canCodes: string[] = [];
    doc.querySelectorAll('Code[packLayer="2"]').forEach((element) => {
      const code = element.getAttribute('curCode') ?? '';
      canCodes.push(code);
      grouped.set(code, []);
    });
    doc.querySelectorAll('Code[packLayer="1"]').forEach((element) => {
      const parent = element.getAttribute('parentCode') ?? '';
      grouped.get(parent)?.push(element.getAttribute('curCode') ?? '');
    });

    const loaded: CanPayload[] = canCodes.map((code, index) => ({
      index: index + 1,
      code,
      plannedParticleCount: grouped.get(code)?.length ?? 0,
      particles: grouped.get(code) ?? [],
    }));

    batchNo.value = batchElement.getAttribute('batchNo') ?? '';
    madeDate.value = batchElement.getAttribute('madeDate') ?? '';
    validateDate.value = batchElement.getAttribute('validateDate') ?? '';
    boxCode.value = boxValue;
    cans.value = loaded;
    issues.value = [];
    errorMessage.value = '';
    conflictOptions.value = [];
  }

  async function runPreview(): Promise<boolean> {
    busy.value = true;
    errorMessage.value = '';
    conflictOptions.value = [];
    try {
      const result = await api.previewXml(toPayload());
      preview.value = result.xml;
      previewSha256.value = result.sha256;
      issues.value = [];
      return true;
    } catch (error) {
      preview.value = '';
      previewSha256.value = '';
      if (error instanceof ApiError) {
        issues.value = error.issues;
        conflictOptions.value = error.options;
        errorMessage.value = error.message;
      } else {
        issues.value = [];
        errorMessage.value = error instanceof Error ? error.message : String(error);
      }
      return false;
    } finally {
      busy.value = false;
    }
  }

  function reset(): void {
    batchNo.value = '';
    madeDate.value = todayIso();
    validateDate.value = todayIso(30);
    boxCode.value = '';
    cans.value = [emptyCan(1)];
    issues.value = [];
    preview.value = '';
    previewSha256.value = '';
    errorMessage.value = '';
    conflictOptions.value = [];
  }

  return {
    batchNo,
    madeDate,
    validateDate,
    boxCode,
    cans,
    issues,
    preview,
    previewSha256,
    busy,
    errorMessage,
    conflictOptions,
    canCount,
    plannedParticleTotal,
    overBatchLimit,
    progressPercent,
    setCanCount,
    clampParticles,
    toPayload,
    loadFromPayload,
    loadFromGoldenXml,
    runPreview,
    reset,
  };
});

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
  type BatchNoConflict,
  type BatchPayload,
  type BatchSummary,
  type CanPayload,
  type EarlyEnd,
  type TransitionOption,
  type XmlImportSummary,
} from '../types/batch';

function todayIso(offsetDays = 0): string {
  const date = new Date();
  date.setDate(date.getDate() + offsetDays);
  return date.toISOString().slice(0, 10);
}

function emptyCan(index: number): CanPayload {
  return { index, code: '', plannedParticleCount: 0, particles: [] };
}

/**
 * 新建罐位时的默认计划粒子数。
 *
 * 取 400 而非上限 2500：真实的 `一箱一罐.xml` 就是 1 罐 400 粒，
 * 默认值贴近实际才不会让操作员每次都手动改。
 */
const DEFAULT_PLANNED_PARTICLES = 400;

export const useBatchStore = defineStore('batch', () => {
  // ---- 已落库批次的元数据 ----
  const batchId = ref('');
  const status = ref('draft');
  const statusLabel = ref('草稿');
  const editable = ref(true);
  const terminal = ref(false);
  const transitions = ref<TransitionOption[]>([]);
  const earlyEnd = ref<EarlyEnd | null>(null);
  const savedBatches = ref<BatchSummary[]>([]);

  // ---- 表单数据 ----
  const batchNo = ref('');
  const madeDate = ref(todayIso());
  const validateDate = ref(todayIso(30));
  const boxCode = ref('');
  const cans = ref<CanPayload[]>([emptyCan(1)]);

  /**
   * 包装结构计划：每罐计划粒子数。与 `cans` 严格区分——
   * `cans` 是扫到的实际数据，这里是界面 2 定的计划。
   */
  const plannedParticleCounts = ref<number[]>([]);

  const issues = ref<BatchIssue[]>([]);
  const preview = ref('');
  const previewSha256 = ref('');
  const busy = ref(false);
  const errorMessage = ref('');
  const conflictOptions = ref<Array<{ action: string; label: string }>>([]);
  const conflict = ref<BatchNoConflict | null>(null);
  const notice = ref('');
  /** 最近一次导入的摘要（导入成功后界面要回显"导入了什么"）。 */
  const importSummary = ref<XmlImportSummary | null>(null);

  /**
   * 待确认的导入内容。
   *
   * 批号冲突时操作员可能选"创建新版本"，那要拿**同一份 XML** 再提交一次；
   * 不先存下来就没法重试（文件已经读进内存但界面上的选择框已经关了）。
   */
  const pendingImport = ref<{ xml: string; sourceName: string } | null>(null);

  const canCount = computed(() => plannedParticleCounts.value.length);
  const plannedParticleTotal = computed(() =>
    plannedParticleCounts.value.reduce((sum, value) => sum + (value || 0), 0),
  );
  const overBatchLimit = computed(() => plannedParticleTotal.value > MAX_PARTICLES_PER_BATCH);
  const progressPercent = computed(() =>
    Math.min(100, Math.round((plannedParticleTotal.value / MAX_PARTICLES_PER_BATCH) * 1000) / 10),
  );

  /** 未保存的新批次（还没有 id）。 */
  const isNew = computed(() => batchId.value === '');

  /** 缺漏粒子数：计划减实际。 */
  const missingParticles = computed(() =>
    Math.max(0, plannedParticleTotal.value - actualParticleTotal.value),
  );

  const actualParticleTotal = computed(() =>
    cans.value.reduce((sum, can) => sum + can.particles.length, 0),
  );

  function setCanCount(count: number): void {
    const clamped = Math.min(MAX_CANS, Math.max(MIN_CANS, Math.trunc(count) || MIN_CANS));
    const next = [...plannedParticleCounts.value];
    while (next.length < clamped) next.push(DEFAULT_PLANNED_PARTICLES);
    next.length = clamped;
    plannedParticleCounts.value = next;
  }

  /** 进入包装结构页时确保至少有一个可编辑的罐位。 */
  function ensurePlan(): void {
    if (plannedParticleCounts.value.length === 0) {
      plannedParticleCounts.value = [DEFAULT_PLANNED_PARTICLES];
    }
  }

  function clampParticles(index: number): void {
    const value = plannedParticleCounts.value[index];
    if (value === undefined) return;
    const clamped = Math.min(MAX_PARTICLES_PER_CAN, Math.max(0, value || 0));
    if (clamped !== value) plannedParticleCounts.value[index] = clamped;
  }

  function toPayload(): BatchPayload {
    return {
      batchNo: batchNo.value.trim(),
      madeDate: madeDate.value,
      validateDate: validateDate.value,
      plannedParticleCounts: [...plannedParticleCounts.value],
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
    plannedParticleCounts.value = [...(payload.plannedParticleCounts ?? [])];
    const loaded = payload.box.cans.map((can) => ({ ...can, particles: [...can.particles] }));
    // 后端对"还没生成包装结构"的草稿会返回 0 个罐；界面必须始终有可编辑的罐位，
    // 否则刚存完草稿就看不到罐数控件了。
    cans.value = loaded.length ? loaded : [emptyCan(1)];
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
    batchId.value = '';
    status.value = 'draft';
    statusLabel.value = '草稿';
    editable.value = true;
    terminal.value = false;
    transitions.value = [];
    earlyEnd.value = null;
    batchNo.value = '';
    madeDate.value = todayIso();
    validateDate.value = todayIso(30);
    boxCode.value = '';
    cans.value = [emptyCan(1)];
    plannedParticleCounts.value = [];
    issues.value = [];
    preview.value = '';
    previewSha256.value = '';
    errorMessage.value = '';
    conflictOptions.value = [];
    conflict.value = null;
    notice.value = '';
  }

  /** 把服务端返回的批次详情同步进 store（状态与数据都以后端为准）。 */
  function applyDetail(detail: {
    id: string;
    status: string;
    statusLabel: string;
    editable: boolean;
    terminal: boolean;
    allowedTransitions: string[];
    earlyEnd: EarlyEnd | null;
    data: BatchPayload;
  }): void {
    batchId.value = detail.id;
    status.value = detail.status;
    statusLabel.value = detail.statusLabel;
    editable.value = detail.editable;
    terminal.value = detail.terminal;
    earlyEnd.value = detail.earlyEnd;
    loadFromPayload(detail.data);
  }

  async function refreshTransitions(): Promise<void> {
    if (!batchId.value) {
      transitions.value = [];
      return;
    }
    try {
      const result = await api.getTransitions(batchId.value);
      transitions.value = result.options;
      status.value = result.status;
      statusLabel.value = result.statusLabel;
      editable.value = result.editable;
      terminal.value = result.terminal;
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        reset();
      }
    }
  }

  async function refreshBatchList(params?: { status?: string; search?: string }): Promise<void> {
    try {
      const result = await api.listBatches(params);
      savedBatches.value = result.items;
    } catch {
      savedBatches.value = [];
    }
  }

  /**
   * 保存草稿。
   *
   * 新建时若批号已存在，服务端返回 409 与三选一；这里只负责把冲突上下文
   * 交给界面，由操作员决定，不代替他做选择。
   */
  async function saveDraft(forceNewVersion = false): Promise<boolean> {
    busy.value = true;
    errorMessage.value = '';
    notice.value = '';
    // 必须在 applyDetail 之前取：applyDetail 会写入 batchId，之后再读 isNew 就永远是 false
    const wasNew = isNew.value;
    try {
      const payload = toPayload();
      const detail = wasNew
        ? await api.createBatch(payload, forceNewVersion)
        : await api.updateBatch(batchId.value, payload);
      applyDetail(detail);
      await refreshTransitions();
      await refreshBatchList();
      notice.value = wasNew ? '批次已创建' : '已保存';
      return true;
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.batchNoConflict && !forceNewVersion) {
          conflict.value = error.batchNoConflict;
          conflictOptions.value = error.options;
          return false;
        }
        issues.value = error.issues;
        errorMessage.value = error.message;
      } else {
        errorMessage.value = error instanceof Error ? error.message : String(error);
      }
      return false;
    } finally {
      busy.value = false;
    }
  }

  async function openExisting(id: string): Promise<boolean> {
    busy.value = true;
    try {
      const detail = await api.getBatch(id);
      applyDetail(detail);
      await refreshTransitions();
      conflict.value = null;
      notice.value = `已打开批次 ${detail.batchNo}`;
      return true;
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : String(error);
      return false;
    } finally {
      busy.value = false;
    }
  }

  /**
   * 导入一份 XML，新建批次并把数据回填进 store。

   * 解析、结构校验、批号唯一性全部在服务端完成；这里只负责三件事：
   * 把文件内容送出去、把冲突交给操作员、把成功结果填回界面。
   */
  async function importXml(
    xml: string,
    sourceName = '',
    forceNewVersion = false,
  ): Promise<boolean> {
    busy.value = true;
    errorMessage.value = '';
    notice.value = '';
    issues.value = [];
    if (!forceNewVersion) {
      conflict.value = null;
      conflictOptions.value = [];
    }
    try {
      const result = await api.importXml({ xml, sourceName, forceNewVersion });
      importSummary.value = result.summary;
      pendingImport.value = null;
      // 回填走后端的批次详情，保证界面显示的就是库里那一份
      await openExisting(result.batchId);
      notice.value = `已导入 ${result.summary.sourceName || 'XML'}：${result.summary.batchNo} · ${result.summary.canCount} 罐 / ${result.summary.particleTotal} 粒`;
      return true;
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.batchNoConflict && !forceNewVersion) {
          pendingImport.value = { xml, sourceName };
          conflict.value = error.batchNoConflict;
          conflictOptions.value = error.options;
          return false;
        }
        issues.value = error.issues;
        errorMessage.value = error.message;
      } else {
        errorMessage.value = error instanceof Error ? error.message : String(error);
      }
      return false;
    } finally {
      busy.value = false;
    }
  }

  /** 冲突里选了"创建新版本"：用同一份 XML 再提交一次。 */
  async function importXmlAsNewVersion(): Promise<boolean> {
    const pending = pendingImport.value;
    if (!pending) return false;
    return importXml(pending.xml, pending.sourceName, true);
  }

  function dismissConflict(): void {
    conflict.value = null;
    conflictOptions.value = [];
    // 取消导入的冲突选择后，待重试的内容也一并丢掉，避免下次误提交旧文件
    pendingImport.value = null;
  }

  async function changeStatus(target: string, reason = '', operator = ''): Promise<boolean> {
    if (!batchId.value) return false;
    busy.value = true;
    errorMessage.value = '';
    try {
      const result = await api.changeStatus(batchId.value, target, reason, operator);
      applyDetail(result.batch);
      await refreshTransitions();
      await refreshBatchList();
      notice.value = `状态已变更为「${result.transition.toLabel}」`;
      return true;
    } catch (error) {
      if (error instanceof ApiError) {
        issues.value = error.issues;
        errorMessage.value = error.message;
      } else {
        errorMessage.value = error instanceof Error ? error.message : String(error);
      }
      return false;
    } finally {
      busy.value = false;
    }
  }

  async function registerEarlyEnd(
    reason: string,
    operator: string,
    note: string,
  ): Promise<boolean> {
    if (!batchId.value) return false;
    busy.value = true;
    errorMessage.value = '';
    try {
      const result = await api.registerEarlyEnd(batchId.value, reason, operator, note);
      applyDetail(result.batch);
      earlyEnd.value = result.earlyEnd;
      notice.value = '已登记提前结束';
      return true;
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : String(error);
      return false;
    } finally {
      busy.value = false;
    }
  }

  async function clearEarlyEnd(): Promise<boolean> {
    if (!batchId.value) return false;
    busy.value = true;
    try {
      const result = await api.clearEarlyEnd(batchId.value);
      applyDetail(result.batch);
      earlyEnd.value = null;
      notice.value = '已撤销提前结束登记';
      return true;
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : String(error);
      return false;
    } finally {
      busy.value = false;
    }
  }

  return {
    batchId,
    status,
    statusLabel,
    editable,
    terminal,
    transitions,
    earlyEnd,
    savedBatches,
    batchNo,
    madeDate,
    validateDate,
    boxCode,
    cans,
    plannedParticleCounts,
    issues,
    preview,
    previewSha256,
    busy,
    errorMessage,
    conflictOptions,
    conflict,
    notice,
    importSummary,
    pendingImport,
    canCount,
    plannedParticleTotal,
    actualParticleTotal,
    missingParticles,
    overBatchLimit,
    progressPercent,
    isNew,
    setCanCount,
    ensurePlan,
    clampParticles,
    toPayload,
    loadFromPayload,
    loadFromGoldenXml,
    runPreview,
    applyDetail,
    refreshTransitions,
    refreshBatchList,
    saveDraft,
    openExisting,
    importXml,
    importXmlAsNewVersion,
    dismissConflict,
    changeStatus,
    registerEarlyEnd,
    clearEarlyEnd,
    reset,
  };
});

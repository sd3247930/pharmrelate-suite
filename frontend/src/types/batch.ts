/** 与后端 API 一致的领域类型（camelCase）。 */

export const PACK_LAYER_BOX = 3;
export const PACK_LAYER_CAN = 2;
export const PACK_LAYER_PARTICLE = 1;

/** 条码层级前缀白名单（实测反推，用于扫入瞬间拦截错层）。 */
export const CODE_PREFIXES: Record<number, string> = {
  [PACK_LAYER_BOX]: '8021761',
  [PACK_LAYER_CAN]: '8021762',
  [PACK_LAYER_PARTICLE]: '8206233',
};

export const CODE_LENGTH = 20;

export const MAX_CANS = 5;
export const MIN_CANS = 1;
export const MAX_PARTICLES_PER_CAN = 2500;
export const MAX_PARTICLES_PER_BATCH = 12500;

export type PackLayer = typeof PACK_LAYER_BOX | typeof PACK_LAYER_CAN | typeof PACK_LAYER_PARTICLE;

export interface CanPayload {
  index: number;
  code: string;
  plannedParticleCount: number;
  particles: string[];
}

export interface BoxPayload {
  code: string;
  cans: CanPayload[];
}

export interface BatchPayload {
  batchNo: string;
  madeDate: string;
  validateDate: string;
  box: BoxPayload;
  /**
   * 包装结构计划：每罐计划粒子数，长度即计划罐数。
   *
   * 与 `box.cans` 严格区分：这里是界面 2 定的**计划**，扫码前就存在；
   * `box.cans` 是界面 3 扫出来的**实际**数据。导出 XML 只用实际数据。
   */
  plannedParticleCounts?: number[];
}

export interface BatchStats {
  canCount: number;
  plannedParticleTotal: number;
  actualParticleTotal: number;
  boxCode: string;
}

export interface XmlPreviewResponse {
  xml: string;
  sha256: string;
  byteLength: number;
  stats: BatchStats;
}

export interface BatchIssue {
  severity: 'error' | 'warning';
  code: string;
  field: string;
  message: string;
}

export interface GoldenInfo {
  name: string;
  byteLength: number;
  sha256: string;
  roundtripOk: boolean;
  batchNo: string | null;
  canCount: number | null;
  particleCount: number | null;
  error: string | null;
}

export interface HealthResponse {
  status: string;
  version: string;
  python: string;
  platform: string;
  goldenDir: string;
  goldenOk: boolean;
  golden: GoldenInfo[];
}

export interface BatchSummary {
  id: string;
  status: string;
  statusLabel: string;
  editable: boolean;
  terminal: boolean;
  allowedTransitions: string[];
  createdAt: string;
  updatedAt: string;
  revision: number;
  batchNo: string;
  madeDate: string;
  validateDate: string;
  canCount: number;
  actualParticleTotal: number;
  plannedParticleTotal: number;
  earlyEnd: EarlyEnd | null;
}

export interface EarlyEnd {
  reason: string;
  operator: string;
  note: string;
  at: string;
  actualCanCount: number;
  actualParticleCount: number;
}

export interface BatchDetail extends BatchSummary {
  data: BatchPayload & { earlyEnd?: EarlyEnd };
}

export interface BatchListResponse {
  items: BatchSummary[];
  total: number;
  statuses: string[];
}

export interface TransitionOption {
  target: string;
  label: string;
  requiresAdmin: boolean;
  requiresReason: boolean;
}

export interface TransitionsResponse {
  status: string;
  statusLabel: string;
  editable: boolean;
  terminal: boolean;
  options: TransitionOption[];
}

export interface ConflictOption {
  action: string;
  label: string;
}

export interface BatchNoConflict {
  reason: string;
  existing: {
    id: string;
    batchNo: string;
    status: string;
    statusLabel: string;
    updatedAt: string;
    canCount: number;
    actualParticleTotal: number;
  };
  suggestedBatchNo: string;
  options: ConflictOption[];
}

/** 生命周期状态 → AppStatusBadge 的 tone。 */
export const STATUS_TONE: Record<string, string> = {
  draft: 'draft',
  collecting: 'collecting',
  pending_review: 'pending',
  verified: 'verified',
  exported: 'exported',
  locked: 'locked',
  archived: 'archived',
  void: 'void',
};

/** 条码层级判定，等价于后端的 classify_code。 */
export function classifyCode(value: string): PackLayer | null {
  if (value.length !== CODE_LENGTH || !/^\d+$/.test(value)) return null;
  for (const [layer, prefix] of Object.entries(CODE_PREFIXES)) {
    if (value.startsWith(prefix)) return Number(layer) as PackLayer;
  }
  return null;
}

export const LAYER_LABELS: Record<number, string> = {
  [PACK_LAYER_BOX]: '箱',
  [PACK_LAYER_CAN]: '罐',
  [PACK_LAYER_PARTICLE]: '粒子',
};

/**
 * 统一 API 客户端。
 *
 * 后端所有错误都返回 { error: { code, message, detail } }，
 * 因此这里只需要处理一种错误形状，并在 ApiError 中把 detail 原样带出，
 * 让上层能把 issues / options 直接渲染给操作员。
 */

import type {
  BatchDetail,
  BatchIssue,
  BatchListResponse,
  BatchNoConflict,
  BatchPayload,
  CameraStatus,
  EarlyEnd,
  HealthResponse,
  ScanSnapshot,
  SlotEditResponse,
  Review,
  ExportRecord,
  TransitionsResponse,
  XmlPreviewResponse,
} from '../types/batch';

export interface ApiErrorBody {
  code: string;
  message: string;
  detail: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: Record<string, unknown>;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = 'ApiError';
    this.status = status;
    this.code = body.code;
    this.detail = body.detail ?? {};
  }

  /** 校验类错误携带的问题清单。 */
  get issues(): BatchIssue[] {
    const value = this.detail.issues;
    return Array.isArray(value) ? (value as BatchIssue[]) : [];
  }

  /** 重复批号的三个可选动作。 */
  get options(): Array<{ action: string; label: string }> {
    const value = this.detail.options;
    return Array.isArray(value) ? (value as Array<{ action: string; label: string }>) : [];
  }

  /** 重复批号冲突的完整上下文。 */
  get batchNoConflict(): BatchNoConflict | null {
    if (this.detail.reason !== 'BATCH_NO_EXISTS' || !this.detail.existing) return null;
    return this.detail as unknown as BatchNoConflict;
  }

  /** 状态机拒绝流转时给出的允许目标。 */
  get allowedTransitions(): string[] {
    const value = this.detail.allowed;
    return Array.isArray(value) ? (value as string[]) : [];
  }
}

/**
 * API 根地址。
 *
 * 浏览器开发态走 Vite 代理（同源 /api，无需处理 CORS）；
 * Tauri 打包态由 `initApiBase()` 从 Rust 侧取到动态分配的端口再覆盖。
 */
let apiBase = '/api';

export function apiBaseUrl(): string {
  return apiBase;
}

export function setApiBase(url: string): void {
  apiBase = url.replace(/\/$/, '');
}

/**
 * 启动时解析真实后端地址。
 *
 * 依次尝试 Electron 预加载桥 → Tauri 命令 → 保持 /api（浏览器开发态走 Vite 代理）。
 * 同一个前端产物因此能在浏览器、Electron、Tauri 三种宿主里运行，不需要分别构建。
 */
export async function initApiBase(): Promise<void> {
  const bridge = (globalThis as { pharmrelate?: { apiBaseUrl?: () => Promise<string> } }).pharmrelate;
  if (bridge?.apiBaseUrl) {
    try {
      const resolved = await bridge.apiBaseUrl();
      if (resolved) {
        setApiBase(resolved);
        return;
      }
    } catch {
      // 落到下一种宿主
    }
  }

  const tauri = (globalThis as { __TAURI__?: { core?: { invoke?: (cmd: string) => Promise<unknown> } } })
    .__TAURI__;
  const invoke = tauri?.core?.invoke;
  if (!invoke) return;
  try {
    const resolved = (await invoke('api_base_url')) as string;
    if (resolved) setApiBase(resolved);
  } catch {
    // 取不到就保持 /api，由界面上的"本地服务未连接"提示暴露问题
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl()}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });

  if (!response.ok) {
    let body: ApiErrorBody = {
      code: 'NETWORK_ERROR',
      message: `请求失败（HTTP ${response.status}）`,
      detail: {},
    };
    try {
      const parsed = (await response.json()) as { error?: ApiErrorBody };
      if (parsed.error) body = parsed.error;
    } catch {
      // 响应体不是 JSON，保留默认信息
    }
    throw new ApiError(response.status, body);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  health: () => request<HealthResponse>('/health'),
  goldenXml: async (name: string): Promise<string> => {
    const response = await fetch(`${apiBaseUrl()}/golden/${encodeURIComponent(name)}/xml`);
    if (!response.ok) {
      throw new ApiError(response.status, {
        code: 'GOLDEN_READ_FAILED',
        message: `读取基准文件 ${name} 失败`,
        detail: { name },
      });
    }
    return response.text();
  },
  previewXml: (payload: BatchPayload) =>
    request<XmlPreviewResponse>('/xml/preview', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  listBatches: (params?: { status?: string; search?: string }) => {
    const query = new URLSearchParams();
    if (params?.status) query.set('status', params.status);
    if (params?.search) query.set('search', params.search);
    const suffix = query.toString() ? `?${query.toString()}` : '';
    return request<BatchListResponse>(`/batches${suffix}`);
  },

  getBatch: (id: string) => request<BatchDetail>(`/batches/${id}`),

  createBatch: (payload: BatchPayload, forceNewVersion = false) =>
    request<BatchDetail>('/batches', {
      method: 'POST',
      body: JSON.stringify({ ...payload, forceNewVersion }),
    }),

  updateBatch: (id: string, payload: BatchPayload) =>
    request<BatchDetail>(`/batches/${id}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),

  getTransitions: (id: string) => request<TransitionsResponse>(`/batches/${id}/transitions`),

  changeStatus: (id: string, target: string, reason = '', operator = '') =>
    request<{ batch: BatchDetail; transition: Record<string, string> }>(
      `/batches/${id}/status`,
      {
        method: 'POST',
        body: JSON.stringify({ target, reason, operator }),
      },
    ),

  registerEarlyEnd: (id: string, reason: string, operator: string, note: string) =>
    request<{ batch: BatchDetail; earlyEnd: EarlyEnd; missingParticles: number }>(
      `/batches/${id}/early-end`,
      {
        method: 'POST',
        body: JSON.stringify({ reason, operator, note }),
      },
    ),

  clearEarlyEnd: (id: string) =>
    request<{ batch: BatchDetail; earlyEnd: null }>(`/batches/${id}/early-end`, {
      method: 'DELETE',
    }),

  storage: () =>
    request<{ databasePath: string; databaseDir: string; exists: boolean; schemaVersion: string }>(
      '/system/storage',
    ),

  // ---------------------------------------------------------------- 扫码
  scanSession: (batchId: string) => request<ScanSnapshot>(`/scan/${batchId}/session`),

  scanFrame: (
    batchId: string,
    codes: string[],
    conflicts: Array<Record<string, unknown>> = [],
  ) =>
    request<ScanSnapshot>(`/scan/${batchId}/frame`, {
      method: 'POST',
      body: JSON.stringify({ codes, conflicts }),
    }),

  scanConfirm: (batchId: string) =>
    request<ScanSnapshot>(`/scan/${batchId}/confirm`, { method: 'POST' }),

  scanRescan: (batchId: string) =>
    request<ScanSnapshot>(`/scan/${batchId}/rescan`, { method: 'POST' }),

  scanNextCan: (batchId: string, proceed: boolean) =>
    request<ScanSnapshot>(`/scan/${batchId}/next-can`, {
      method: 'POST',
      body: JSON.stringify({ proceed }),
    }),

  scanReset: (batchId: string) =>
    request<ScanSnapshot>(`/scan/${batchId}/reset`, { method: 'POST' }),

  // ------------------------------------------------------------ 槽位编辑
  slotDelete: (batchId: string, code: string) =>
    request<SlotEditResponse>(`/batches/${batchId}/slots/delete`, {
      method: 'POST',
      body: JSON.stringify({ code }),
    }),

  slotReplace: (batchId: string, code: string, newCode: string) =>
    request<SlotEditResponse>(`/batches/${batchId}/slots/replace`, {
      method: 'POST',
      body: JSON.stringify({ code, newCode }),
    }),

  clearCan: (batchId: string, canIndex: number) =>
    request<SlotEditResponse>(`/batches/${batchId}/cans/${canIndex}/clear`, {
      method: 'POST',
    }),

  rescanCan: (batchId: string, canIndex: number, newCanCode: string) =>
    request<SlotEditResponse>(`/batches/${batchId}/cans/${canIndex}/rescan`, {
      method: 'POST',
      body: JSON.stringify({ newCanCode }),
    }),

  rescanBox: (batchId: string, newBoxCode = '') =>
    request<SlotEditResponse>(`/batches/${batchId}/box/rescan`, {
      method: 'POST',
      body: JSON.stringify({ newBoxCode }),
    }),

  scanUndo: (batchId: string) =>
    request<SlotEditResponse>(`/batches/${batchId}/undo`, { method: 'POST' }),

  scanRedo: (batchId: string) =>
    request<SlotEditResponse>(`/batches/${batchId}/redo`, { method: 'POST' }),

  review: (batchId: string) => request<Review>(`/batches/${batchId}/review`),

  runExport: (batchId: string, kinds: Array<'xml' | 'html'>) =>
    request<{ items: ExportRecord[]; exportKind: string }>(`/batches/${batchId}/export`, {
      method: 'POST',
      body: JSON.stringify({ kinds }),
    }),

  exportHistory: (batchId: string) =>
    request<{ items: ExportRecord[]; total: number }>(`/batches/${batchId}/exports`),

  // -------------------------------------------------------------- 摄像头
  cameraStatus: () => request<CameraStatus>('/camera/status'),

  cameraStart: (options: {
    kind: 'opencv' | 'test_image';
    deviceIndex?: number;
    images?: string[];
    batchId?: string;
    maxWidth?: number;
    recognizeIntervalMs?: number;
  }) =>
    request<CameraStatus>('/camera/start', {
      method: 'POST',
      body: JSON.stringify(options),
    }),

  cameraStop: () => request<CameraStatus>('/camera/stop', { method: 'POST' }),

  cameraDevices: () =>
    request<{ items: Array<{ index: number; width: number; height: number }> }>(
      '/camera/devices',
    ),
};

/** 摄像头预览是图片流，不能走 JSON 客户端。 */
export function cameraFrameUrl(cacheBuster: number): string {
  return `${apiBaseUrl()}/camera/frame.jpg?t=${cacheBuster}`;
}

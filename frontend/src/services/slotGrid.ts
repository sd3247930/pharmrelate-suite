/**
 * 网格抽象层：全部是纯函数，**不依赖任何 DOM**。

 * 为什么单独抽出来：阶段 3.4 的交互（选择槽位、替换、删除、高亮）与阶段 3.3 的
 * 虚拟化渲染是两件事。交互先按"槽位数组 + 视口窗口"定义好，3.3 换渲染方式
 * （虚拟滚动 / Canvas）时只需要换显示层，交互逻辑一行不动。

 * 虚拟窗口计算也放在这里：它同样是纯数学，可以脱离浏览器直接测。
 */

import type { CanPayload } from '../types/batch';

export type SlotStatus = 'scanned' | 'empty' | 'conflict';

export interface Slot {
  /** 在本罐内的序号，从 1 开始。 */
  index: number;
  /** 罐序号，从 1 开始。 */
  canIndex: number;
  /** 罐号，可能为空（该罐还没扫）。 */
  canCode: string;
  code: string | null;
  status: SlotStatus;
}

/**
 * 按"计划"铺出槽位。

 * 槽位来自计划（每罐几粒），条码来自实际扫描结果 —— 计划与实际必须分开，
 * 否则"缺漏了几个槽位"根本无从计算。
 */
export function buildSlots(plan: number[], cans: CanPayload[]): Slot[] {
  const slots: Slot[] = [];
  plan.forEach((planned, canOffset) => {
    const canIndex = canOffset + 1;
    const can = cans.find((item) => item.index === canIndex);
    const particles = can?.particles ?? [];
    const count = Math.max(planned, particles.length);

    for (let slot = 0; slot < count; slot += 1) {
      const code = particles[slot] ?? null;
      slots.push({
        index: slot + 1,
        canIndex,
        canCode: can?.code ?? '',
        code,
        // 超出计划的多余粒子标为冲突：正常流程不该出现，出现即说明数据有问题
        status: code ? (slot < planned ? 'scanned' : 'conflict') : 'empty',
      });
    }
  });
  return slots;
}

/** 只取某一罐的槽位。 */
export function slotsOfCan(slots: Slot[], canIndex: number): Slot[] {
  return slots.filter((slot) => slot.canIndex === canIndex);
}

export function findSlotByCode(slots: Slot[], code: string): Slot | null {
  return slots.find((slot) => slot.code === code) ?? null;
}

export interface SlotSummary {
  total: number;
  scanned: number;
  empty: number;
  conflict: number;
  complete: boolean;
  missing: number;
}

export function summarizeSlots(slots: Slot[]): SlotSummary {
  const scanned = slots.filter((slot) => slot.status === 'scanned').length;
  const empty = slots.filter((slot) => slot.status === 'empty').length;
  const conflict = slots.filter((slot) => slot.status === 'conflict').length;
  return {
    total: slots.length,
    scanned,
    empty,
    conflict,
    complete: slots.length > 0 && empty === 0 && conflict === 0,
    missing: empty,
  };
}

export interface GridGeometry {
  columns: number;
  rowHeight: number;
  viewportHeight: number;
  overscanRows?: number;
}

export interface VisibleRange {
  startIndex: number;
  endIndex: number;
  /** 渲染容器的高度，用于把滚动条撑到正确长度。 */
  totalHeight: number;
  offsetY: number;
}

/**
 * 计算虚拟窗口。

 * 只返回"要渲染哪一段"，不碰 DOM。3.3 无论用绝对定位、transform 还是 Canvas，
 * 都直接消费这个结果。
 *
 * 12500 个槽位、每行 8 列 = 1563 行；这个函数保证无论总量多大，
 * 每帧最多只渲染视口内 + overscan 的那几十行。
 */
export function visibleRange(
  totalSlots: number,
  scrollTop: number,
  geometry: GridGeometry,
): VisibleRange {
  const columns = Math.max(1, Math.floor(geometry.columns));
  const rowHeight = Math.max(1, geometry.rowHeight);
  const viewportHeight = Math.max(0, geometry.viewportHeight);
  const overscan = Math.max(0, geometry.overscanRows ?? 2);

  const totalRows = Math.ceil(Math.max(0, totalSlots) / columns);
  const totalHeight = totalRows * rowHeight;
  const firstVisibleRow = Math.floor(Math.max(0, scrollTop) / rowHeight);
  const visibleRows = Math.ceil(viewportHeight / rowHeight) + 1;

  const startRow = Math.max(0, firstVisibleRow - overscan);
  const endRow = Math.min(totalRows, firstVisibleRow + visibleRows + overscan);

  return {
    startIndex: Math.min(totalSlots, startRow * columns),
    endIndex: Math.min(totalSlots, endRow * columns),
    totalHeight,
    offsetY: startRow * rowHeight,
  };
}

/**
 * 从条码反查它属于哪一罐的哪个槽位。

 * 重复扫码被拒绝时，界面要告诉操作员"它已经绑在哪儿"，
 * 而不是只报一句"条码重复"。
 */
export function locateCode(slots: Slot[], code: string): string {
  const slot = findSlotByCode(slots, code);
  if (!slot) return '';
  return `罐 ${slot.canIndex} / 粒子槽位 ${slot.index}`;
}

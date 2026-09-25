/**
 * 网格抽象层测试。全部脱离 DOM 运行 —— 这正是把它抽出来的目的：
 * 交互与虚拟窗口计算可以独立于任何渲染方式被验证。
 */

import { describe, expect, it } from 'vitest';

import {
  buildSlots,
  findSlotByCode,
  locateCode,
  slotsOfCan,
  summarizeSlots,
  visibleRange,
} from './slotGrid';
import type { CanPayload } from '../types/batch';

function can(index: number, code: string, particles: string[]): CanPayload {
  return { index, code, plannedParticleCount: particles.length, particles };
}

describe('buildSlots', () => {
  it('按计划铺出空槽位，并填入已扫到的条码', () => {
    const slots = buildSlots([3, 2], [can(1, 'C1', ['A', 'B'])]);
    expect(slots).toHaveLength(5);
    expect(slots[0]).toMatchObject({ index: 1, canIndex: 1, code: 'A', status: 'scanned' });
    expect(slots[2]).toMatchObject({ index: 3, canIndex: 1, code: null, status: 'empty' });
    // 罐 2 还没扫，两个槽位都应存在且为空
    expect(slots[3]).toMatchObject({ canIndex: 2, code: null, status: 'empty' });
    expect(slots[4]).toMatchObject({ canIndex: 2, code: null, status: 'empty' });
  });

  it('槽位数来自计划，不受实际扫描数量影响', () => {
    const slots = buildSlots([2500], [can(1, 'C1', ['A'])]);
    expect(slots).toHaveLength(2500);
    expect(summarizeSlots(slots).missing).toBe(2499);
  });

  it('实际多于计划时多出来的槽位标为冲突，而不是悄悄消失', () => {
    const slots = buildSlots([1], [can(1, 'C1', ['A', 'B'])]);
    expect(slots).toHaveLength(2);
    expect(slots[1].status).toBe('conflict');
    expect(summarizeSlots(slots).conflict).toBe(1);
  });

  it('空计划不产生槽位', () => {
    expect(buildSlots([], [])).toEqual([]);
  });
});

describe('summarizeSlots', () => {
  it('统计已扫 / 缺漏 / 冲突', () => {
    const slots = buildSlots([2, 2], [can(1, 'C1', ['A']), can(2, 'C2', ['B', 'C'])]);
    const summary = summarizeSlots(slots);
    expect(summary).toMatchObject({ total: 4, scanned: 3, empty: 1, conflict: 0, missing: 1 });
    expect(summary.complete).toBe(false);
  });

  it('全部扫满才算完成', () => {
    const slots = buildSlots([2], [can(1, 'C1', ['A', 'B'])]);
    expect(summarizeSlots(slots).complete).toBe(true);
  });

  it('没有槽位时不算完成', () => {
    expect(summarizeSlots([]).complete).toBe(false);
  });
});

describe('定位', () => {
  it('按条码反查所属槽位，用于提示"它已经绑在哪儿"', () => {
    const slots = buildSlots([2, 2], [can(1, 'C1', ['A']), can(2, 'C2', ['B'])]);
    expect(findSlotByCode(slots, 'B')).toMatchObject({ canIndex: 2, index: 1 });
    expect(locateCode(slots, 'B')).toBe('罐 2 / 粒子槽位 1');
    expect(locateCode(slots, '不存在')).toBe('');
  });

  it('可以按罐取槽位', () => {
    const slots = buildSlots([2, 2], []);
    expect(slotsOfCan(slots, 2)).toHaveLength(2);
    expect(slotsOfCan(slots, 2).every((slot) => slot.canIndex === 2)).toBe(true);
  });
});

describe('visibleRange 虚拟窗口', () => {
  const geometry = { columns: 8, rowHeight: 20, viewportHeight: 200, overscanRows: 2 };

  it('只渲染视口内的行，再加上少量 overscan', () => {
    const range = visibleRange(12500, 0, geometry);
    // 视口 200px / 行高 20 = 10 行，加 1 行余量 + 2 行 overscan，共 13 行 = 104 槽位
    expect(range.startIndex).toBe(0);
    expect(range.endIndex).toBe(104);
    expect(range.endIndex).toBeLessThan(200);
  });

  it('滚动到中段时窗口跟着移动', () => {
    const range = visibleRange(12500, 2000, geometry);
    expect(range.startIndex).toBe(8 * (100 - 2));
    expect(range.offsetY).toBe((100 - 2) * 20);
  });

  it('总高度按全部槽位算，滚动条长度正确', () => {
    const range = visibleRange(12500, 0, geometry);
    expect(range.totalHeight).toBe(Math.ceil(12500 / 8) * 20);
  });

  it('滚到底部不会越界', () => {
    const range = visibleRange(12500, 100000, geometry);
    expect(range.endIndex).toBeLessThanOrEqual(12500);
    expect(range.startIndex).toBeLessThanOrEqual(range.endIndex);
  });

  it('槽位很少时也不会算出负数或越界', () => {
    const range = visibleRange(3, 0, geometry);
    expect(range.startIndex).toBe(0);
    expect(range.endIndex).toBe(3);
  });

  it('空网格是安全的', () => {
    const range = visibleRange(0, 0, geometry);
    expect(range).toMatchObject({ startIndex: 0, endIndex: 0, totalHeight: 0 });
  });

  it('12500 槽位下渲染量仍然很小', () => {
    const range = visibleRange(12500, 16000, geometry);
    // 每帧最多渲染 (视口行数 + 1 行余量 + 两侧 overscan) 行 = 11 + 1 + 4 = 15 行 = 120 槽位
    const maxRows =
      Math.ceil(geometry.viewportHeight / geometry.rowHeight) + 1 + geometry.overscanRows * 2;
    expect(range.endIndex - range.startIndex).toBeLessThanOrEqual(geometry.columns * maxRows);
    // 与 12500 的总量相比微不足道，这才是虚拟化的意义
    expect(range.endIndex - range.startIndex).toBeLessThan(12500 * 0.02);
  });
});

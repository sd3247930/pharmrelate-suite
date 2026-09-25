/**
 * 虚拟化槽位网格测试。

 * 核心要验证的是**渲染量不随槽位总数增长**：12500 个槽位必须只渲染视口内的
 * 那几十个节点。这是 V1.1 44 章"不允许一次性创建重型 DOM"的直接检验手段，
 * 也是唯一能在单元层面把它测出来的方式（性能只能靠 E2E，但节点数可以在这里数）。
 */

import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';

import AppSlotGrid from './AppSlotGrid.vue';
import type { Slot } from '../services/slotGrid';

function makeSlots(count: number, scanned = 0): Slot[] {
  return Array.from({ length: count }, (_item, index) => ({
    index: index + 1,
    canIndex: 1,
    canCode: 'C1',
    code: index < scanned ? `CODE-${index}` : null,
    status: index < scanned ? 'scanned' : 'empty',
  }));
}

describe('AppSlotGrid', () => {
  it('12500 槽位只渲染视口内的少量节点', () => {
    const wrapper = mount(AppSlotGrid, {
      props: { slots: makeSlots(12500), height: 220, minSlotWidth: 64 },
      attachTo: document.body,
    });

    const rendered = wrapper.findAll('.slot-grid__slot').length;
    expect(rendered).toBeGreaterThan(0);
    expect(rendered).toBeLessThan(300);
    expect(rendered).toBeLessThan(12500 * 0.05);
  });

  it('滚动容器高度按全部槽位撑开，滚动条长度正确', () => {
    const wrapper = mount(AppSlotGrid, {
      props: { slots: makeSlots(12500), height: 220, minSlotWidth: 64, rowHeight: 30 },
      attachTo: document.body,
    });
    const canvas = wrapper.find('.slot-grid__canvas');
    const height = Number.parseInt((canvas.element as HTMLElement).style.height, 10);
    expect(height).toBeGreaterThan(1000);
  });

  it('槽位少时如实渲染', () => {
    const wrapper = mount(AppSlotGrid, {
      props: { slots: makeSlots(3), height: 220, minSlotWidth: 64 },
      attachTo: document.body,
    });
    expect(wrapper.findAll('.slot-grid__slot')).toHaveLength(3);
  });

  it('点击槽位向外抛出 select 事件', async () => {
    const wrapper = mount(AppSlotGrid, {
      props: { slots: makeSlots(4), height: 220, minSlotWidth: 64 },
      attachTo: document.body,
    });
    await wrapper.findAll('.slot-grid__slot')[2].trigger('click');
    const emitted = wrapper.emitted('select');
    expect(emitted).toHaveLength(1);
    expect((emitted?.[0]?.[0] as Slot).index).toBe(3);
  });

  it('已扫描 / 空槽 / 异常用不同类名表达，且都带序号文字', () => {
    const slots = makeSlots(3, 1);
    slots[2] = { ...slots[2], status: 'conflict', code: 'X' };
    const wrapper = mount(AppSlotGrid, {
      props: { slots, height: 220, minSlotWidth: 64 },
      attachTo: document.body,
    });
    expect(wrapper.find('.slot-grid__slot.is-scanned').exists()).toBe(true);
    expect(wrapper.find('.slot-grid__slot.is-empty').exists()).toBe(true);
    expect(wrapper.find('.slot-grid__slot.is-conflict').exists()).toBe(true);
    // 颜色不是唯一线索：每个槽位都有序号文字
    expect(wrapper.findAll('.slot-grid__slot')[0].text()).toContain('0001');
  });

  it('暴露 scrollToIndex 用于按条码定位', () => {
    const wrapper = mount(AppSlotGrid, {
      props: { slots: makeSlots(12500), height: 220, minSlotWidth: 64 },
      attachTo: document.body,
    });
    expect(typeof wrapper.vm.scrollToIndex).toBe('function');
    wrapper.vm.scrollToIndex(6400);
    const scroller = wrapper.find('.slot-grid').element as HTMLElement;
    expect(scroller.scrollTop).toBeGreaterThan(0);
  });
});

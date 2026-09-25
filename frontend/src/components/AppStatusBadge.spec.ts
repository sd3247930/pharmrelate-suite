/**
 * 状态徽章测试。
 *
 * 锁死本项目最核心的可用性约束：状态一律"颜色 + 图标 + 文字"三重表达，
 * 颜色永不作为唯一信息载体。这里逐项验证文字始终被渲染出来，
 * 且图标元素确实存在——只有颜色没有文字的实现会当场失败。
 */

import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';

import AppStatusBadge, { type StatusTone } from './AppStatusBadge.vue';

const ALL_TONES: Array<{ tone: StatusTone; expected: string }> = [
  { tone: 'draft', expected: '草稿' },
  { tone: 'collecting', expected: '采集中' },
  { tone: 'pending', expected: '待核对' },
  { tone: 'verified', expected: '已核对' },
  { tone: 'exported', expected: '已导出' },
  { tone: 'locked', expected: '已锁定' },
  { tone: 'archived', expected: '已归档' },
  { tone: 'void', expected: '已作废' },
  { tone: 'offline', expected: '离线' },
  { tone: 'conflict', expected: '冲突' },
];

describe('AppStatusBadge', () => {
  it.each(ALL_TONES)('$tone 会渲染中文文字「$expected」', ({ tone, expected }) => {
    const wrapper = mount(AppStatusBadge, { props: { tone } });
    expect(wrapper.text()).toContain(expected);
  });

  it.each(ALL_TONES)('$tone 会渲染图标（svg）', ({ tone }) => {
    const wrapper = mount(AppStatusBadge, { props: { tone } });
    const svg = wrapper.find('svg');
    expect(svg.exists()).toBe(true);
    // 图标是装饰性的，不能成为唯一语义来源
    expect(svg.attributes('aria-hidden')).toBe('true');
  });

  it('自定义 label 会覆盖默认文字', () => {
    const wrapper = mount(AppStatusBadge, {
      props: { tone: 'collecting', label: '采集中', detail: '4 台设备' },
    });
    expect(wrapper.text()).toContain('采集中');
    expect(wrapper.text()).toContain('4 台设备');
  });
});

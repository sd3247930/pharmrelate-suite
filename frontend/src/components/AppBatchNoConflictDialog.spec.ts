/**
 * 重复批号三选一弹窗测试。
 *
 * 这是 V1.1 8.4 的硬要求：不能只报「批号重复」就把操作员挡死，
 * 必须给出三条明确出路。这里验证三个动作各自只触发对应的一个事件，
 * 避免按钮接错线。
 */

import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';

import AppBatchNoConflictDialog from './AppBatchNoConflictDialog.vue';
import type { BatchNoConflict } from '../types/batch';

const CONFLICT: BatchNoConflict = {
  reason: 'BATCH_NO_EXISTS',
  existing: {
    id: 'a1b2c3d4',
    batchNo: '20260901',
    status: 'collecting',
    statusLabel: '采集中',
    updatedAt: '2026-09-25T22:31:00+00:00',
    canCount: 3,
    actualParticleTotal: 4,
  },
  suggestedBatchNo: '20260901-V2',
  options: [
    { action: 'open_existing', label: '打开已有批次' },
    { action: 'create_new_version', label: '创建新版本 20260901-V2' },
    { action: 'cancel', label: '取消并返回修改' },
  ],
};

function mountDialog() {
  return mount(AppBatchNoConflictDialog, {
    props: { modelValue: true, conflict: CONFLICT, busy: false },
  });
}

describe('AppBatchNoConflictDialog', () => {
  it('标题说明发生了什么，而不是只抛「批号重复」', () => {
    expect(mountDialog().text()).toContain('检测到批号已存在');
  });

  it('给出已有批次的关键信息，便于判断该打开还是另存', () => {
    const text = mountDialog().text();
    expect(text).toContain('20260901');
    expect(text).toContain('采集中');
    expect(text).toContain('3 罐 / 4 粒');
  });

  it('列出三条出路，且新版本号由服务端建议值决定', () => {
    const text = mountDialog().text();
    expect(text).toContain('打开已有批次');
    expect(text).toContain('创建新版本 20260901-V2');
    expect(text).toContain('取消并返回修改');
  });

  it('点击「打开已有批次」只触发 openExisting', async () => {
    const wrapper = mountDialog();
    const button = wrapper.findAll('button').find((item) => item.text().includes('打开已有批次'));
    expect(button).toBeTruthy();
    await button!.trigger('click');
    expect(wrapper.emitted('openExisting')).toHaveLength(1);
    expect(wrapper.emitted('createNewVersion')).toBeUndefined();
    expect(wrapper.emitted('cancel')).toBeUndefined();
  });

  it('点击「创建新版本」只触发 createNewVersion', async () => {
    const wrapper = mountDialog();
    const button = wrapper.findAll('button').find((item) => item.text().includes('创建新版本'));
    await button!.trigger('click');
    expect(wrapper.emitted('createNewVersion')).toHaveLength(1);
    expect(wrapper.emitted('openExisting')).toBeUndefined();
  });

  it('点击「取消并返回修改」只触发 cancel', async () => {
    const wrapper = mountDialog();
    const button = wrapper.findAll('button').find((item) => item.text().includes('取消并返回修改'));
    await button!.trigger('click');
    expect(wrapper.emitted('cancel')).toHaveLength(1);
    expect(wrapper.emitted('openExisting')).toBeUndefined();
    expect(wrapper.emitted('createNewVersion')).toBeUndefined();
  });
});

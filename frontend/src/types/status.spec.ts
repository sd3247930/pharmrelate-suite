/**
 * 状态映射测试：后端返回的 8 个生命周期状态，前端都要能映射到徽章语义。
 * 漏一个就会在界面上退化成"未知状态"，这类问题在这里拦住。
 */

import { describe, expect, it } from 'vitest';

import { STATUS_TONE } from './batch';

const BACKEND_STATUSES = [
  'draft',
  'collecting',
  'pending_review',
  'verified',
  'exported',
  'locked',
  'archived',
  'void',
];

describe('STATUS_TONE', () => {
  it('覆盖后端全部生命周期状态', () => {
    expect(Object.keys(STATUS_TONE).sort()).toEqual([...BACKEND_STATUSES].sort());
  });

  it('映射到 AppStatusBadge 支持的 tone', () => {
    const supported = new Set([
      'draft',
      'collecting',
      'pending',
      'verified',
      'exported',
      'locked',
      'archived',
      'void',
      'offline',
      'conflict',
    ]);
    for (const tone of Object.values(STATUS_TONE)) {
      expect(supported.has(tone)).toBe(true);
    }
  });
});

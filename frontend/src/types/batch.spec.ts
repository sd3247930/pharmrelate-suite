/**
 * 条码层级规则测试。
 *
 * 前端这份判定逻辑必须与后端 app.domain.constants.classify_code 行为一致，
 * 否则会出现"前端放行、后端拒绝"的不一致体验。
 * 用例与后端 tests/test_phase0_rules.py 中的前缀用例一一对应。
 */

import { describe, expect, it } from 'vitest';

import {
  CODE_LENGTH,
  MAX_PARTICLES_PER_BATCH,
  MAX_PARTICLES_PER_CAN,
  PACK_LAYER_BOX,
  PACK_LAYER_CAN,
  PACK_LAYER_PARTICLE,
  classifyCode,
} from './batch';

describe('classifyCode', () => {
  it('按前缀识别三个层级', () => {
    expect(classifyCode('80217619000000001003')).toBe(PACK_LAYER_BOX);
    expect(classifyCode('80217629000000001005')).toBe(PACK_LAYER_CAN);
    expect(classifyCode('82062339000000001004')).toBe(PACK_LAYER_PARTICLE);
  });

  it('拒绝长度不对、含非数字、前缀未知的输入', () => {
    expect(classifyCode('8021761000001412585')).toBeNull(); // 19 位
    expect(classifyCode('802176190000000010030')).toBeNull(); // 21 位
    expect(classifyCode('8021761000001412585a')).toBeNull();
    expect(classifyCode('12345678901234567890')).toBeNull();
    expect(classifyCode('')).toBeNull();
  });

  it('拒绝全角数字', () => {
    const fullwidth = '８０２１７６１０００００１４１２５８５６';
    expect(fullwidth.length).toBe(CODE_LENGTH);
    expect(classifyCode(fullwidth)).toBeNull();
  });

  it('照片实测的 6 枚追溯码都是合法粒子码', () => {
    const serials = [
      '0000110295569',
      '0000110307353',
      '0000110313029',
      '0000110265841',
      '0000110271913',
      '0000110280860',
    ];
    for (const serial of serials) {
      const code = `8206233${serial}`;
      expect(code).toHaveLength(CODE_LENGTH);
      expect(classifyCode(code)).toBe(PACK_LAYER_PARTICLE);
    }
    expect(new Set(serials).size).toBe(serials.length);
  });
});

describe('规模边界', () => {
  it('与 V1.1 第 13 章一致', () => {
    expect(MAX_PARTICLES_PER_CAN).toBe(2500);
    expect(MAX_PARTICLES_PER_BATCH).toBe(12500);
  });
});

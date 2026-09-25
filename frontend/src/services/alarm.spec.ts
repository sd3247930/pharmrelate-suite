/**
 * 声音报警服务测试。

 * 测试环境没有真实音频设备，因此验证的是**决策逻辑**：
 * 什么情况该响、什么情况不该响、设置能否持久化、未解锁时会不会假装响了。
 * 实际音效需要在有扬声器的机器上人工确认。
 */

import { beforeEach, describe, expect, it } from 'vitest';

import {
  TONES,
  __resetAlarmForTest,
  getAlarmSettings,
  playAlarm,
  unlockAudio,
  updateAlarmSettings,
} from './alarm';

describe('音型定义', () => {
  it('每种事件都有明确的音型', () => {
    for (const tone of [
      'scan-success',
      'scan-warning',
      'scan-error',
      'sync-success',
      'sync-error',
    ] as const) {
      const spec = TONES[tone];
      expect(spec.frequencies.length).toBeGreaterThan(0);
      expect(spec.durationMs).toBeGreaterThan(0);
    }
  });

  it('异常音比成功音更重更长 —— 车间噪音大，异常必须盖得住', () => {
    const success = TONES['scan-success'];
    const error = TONES['scan-error'];
    const successTotal = success.frequencies.length * (success.durationMs + success.gapMs);
    const errorTotal = error.frequencies.length * (error.durationMs + error.gapMs);
    expect(errorTotal).toBeGreaterThan(successTotal);
    expect(Math.min(...error.frequencies)).toBeLessThan(Math.min(...success.frequencies));
  });
});

describe('设置', () => {
  beforeEach(() => {
    __resetAlarmForTest();
    localStorage.clear();
  });

  it('默认开启且音量适中', () => {
    const settings = getAlarmSettings();
    expect(settings.enabled).toBe(true);
    expect(settings.volume).toBeGreaterThan(0);
    expect(settings.volume).toBeLessThanOrEqual(1);
  });

  it('修改后落 localStorage，下次启动仍生效', () => {
    updateAlarmSettings({ enabled: false, volume: 0.25 });
    expect(localStorage.getItem('pharmrelate.alarm')).toContain('"enabled":false');
    expect(getAlarmSettings()).toEqual({ enabled: false, volume: 0.25 });
  });

  it('音量被夹在 0～1 之间', () => {
    expect(updateAlarmSettings({ volume: 5 }).volume).toBe(1);
    expect(updateAlarmSettings({ volume: -3 }).volume).toBe(0);
  });

  it('localStorage 内容损坏时退回默认值，不抛异常', () => {
    localStorage.setItem('pharmrelate.alarm', '{ 这不是 JSON');
    __resetAlarmForTest();
    expect(getAlarmSettings().enabled).toBe(true);
  });
});

describe('播放', () => {
  beforeEach(() => {
    __resetAlarmForTest();
    localStorage.clear();
  });

  it('未解锁时返回 false，不假装响过', () => {
    expect(playAlarm('scan-error')).toBe(false);
  });

  it('关闭声音后即使已解锁也不响', () => {
    updateAlarmSettings({ enabled: false });
    unlockAudio();
    expect(playAlarm('scan-error')).toBe(false);
  });
});

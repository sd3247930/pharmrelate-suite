/**
 * 声音报警服务（V1.1 56 章）。

 * 之所以用 WebAudio 实时合成而不是放音频文件：
 *   - 不引入二进制资源，打包体积不变；
 *   - 音高/时长可调，方便按现场噪音环境调整；
 *   - 离线可用，不依赖网络加载。
 *
 * 浏览器策略要求音频必须由用户手势解锁，因此 AudioContext 延迟到第一次
 * 真实交互时创建，并在界面上明确提示"点击启用声音"。
 */

export type AlarmTone = 'scan-success' | 'scan-warning' | 'scan-error' | 'sync-success' | 'sync-error';

interface ToneSpec {
  frequencies: number[];
  durationMs: number;
  gapMs: number;
  type: OscillatorType;
}

/**
 * 每种事件的音型。
 *
 * 单声高音=成功（容易被忽略也无害）；双声中音=需要看一眼；低频长音=必须处理。
 * 车间噪音大，成功音刻意做得轻，异常音做得重且长。
 */
export const TONES: Record<AlarmTone, ToneSpec> = {
  'scan-success': { frequencies: [880], durationMs: 70, gapMs: 0, type: 'sine' },
  'scan-warning': { frequencies: [660, 660], durationMs: 110, gapMs: 70, type: 'square' },
  'scan-error': { frequencies: [220, 180], durationMs: 260, gapMs: 90, type: 'sawtooth' },
  'sync-success': { frequencies: [990], durationMs: 60, gapMs: 0, type: 'sine' },
  'sync-error': { frequencies: [330, 260], durationMs: 200, gapMs: 80, type: 'square' },
};

const STORAGE_KEY = 'pharmrelate.alarm';

export interface AlarmSettings {
  enabled: boolean;
  /** 0～1。 */
  volume: number;
}

const DEFAULT_SETTINGS: AlarmSettings = { enabled: true, volume: 0.6 };

let context: AudioContext | null = null;
let settings: AlarmSettings = loadSettings();
let unlocked = false;

function loadSettings(): AlarmSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_SETTINGS };
    const parsed = JSON.parse(raw) as Partial<AlarmSettings>;
    return {
      enabled: parsed.enabled ?? DEFAULT_SETTINGS.enabled,
      volume: Math.min(1, Math.max(0, parsed.volume ?? DEFAULT_SETTINGS.volume)),
    };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export function getAlarmSettings(): AlarmSettings {
  return { ...settings };
}

export function updateAlarmSettings(patch: Partial<AlarmSettings>): AlarmSettings {
  settings = {
    enabled: patch.enabled ?? settings.enabled,
    volume: Math.min(1, Math.max(0, patch.volume ?? settings.volume)),
  };
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // 隐私模式等场景下写不进去，不影响本次会话内生效
  }
  return getAlarmSettings();
}

export function isUnlocked(): boolean {
  return unlocked;
}

/** 由第一次用户交互调用（点击"启用声音"或任意扫描按钮）。 */
export function unlockAudio(): boolean {
  try {
    const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return false;
    context = context ?? new Ctor();
    void context.resume();
    unlocked = true;
    return true;
  } catch {
    unlocked = false;
    return false;
  }
}

export function playAlarm(tone: AlarmTone): boolean {
  if (!settings.enabled || !unlocked || !context) return false;
  const spec = TONES[tone];
  let offset = 0;

  for (const frequency of spec.frequencies) {
    const start = context.currentTime + offset / 1000;
    const stop = start + spec.durationMs / 1000;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = spec.type;
    oscillator.frequency.value = frequency;
    // 淡入淡出，避免爆音
    gain.gain.setValueAtTime(0, start);
    gain.gain.linearRampToValueAtTime(settings.volume, start + 0.01);
    gain.gain.setValueAtTime(settings.volume, Math.max(start + 0.01, stop - 0.02));
    gain.gain.linearRampToValueAtTime(0, stop);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start(start);
    oscillator.stop(stop);
    offset += spec.durationMs + spec.gapMs;
  }
  return true;
}

/** 仅供测试：重置模块级状态。 */
export function __resetAlarmForTest(): void {
  context = null;
  unlocked = false;
  settings = { ...DEFAULT_SETTINGS };
}

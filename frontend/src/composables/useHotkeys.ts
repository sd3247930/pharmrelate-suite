/**
 * 全局快捷键。

 * 两条约束：
 *   1. **输入框里不抢键**。操作员正在敲条码时按到组合键，不该触发页面动作；
 *      但 Ctrl+Z 这类"撤销输入"在输入框里有原生含义，也不该被页面吃掉。
 *   2. 快捷键只是加速手段，**不能是唯一入口** —— 每个快捷键对应的按钮都在界面上存在。
 */

import { onBeforeUnmount, onMounted } from 'vue';

export interface Hotkey {
  /** 例如 'ctrl+z'、'ctrl+shift+z'、'f5'、'escape'。 */
  combo: string;
  handler: () => void;
  /** 允许在输入框内触发。默认 false。 */
  allowInInput?: boolean;
}

function normalize(event: KeyboardEvent): string {
  const parts: string[] = [];
  if (event.ctrlKey) parts.push('ctrl');
  if (event.altKey) parts.push('alt');
  if (event.shiftKey) parts.push('shift');

  const key = event.key.toLowerCase();
  // 组合键里 Ctrl+Shift+Z 与 Ctrl+Z 的 event.key 分别是 'z' 与 'z'，
  // 因此不能依赖 key 的大小写来区分，统一小写再靠 shift 标记区分。
  parts.push(key === ' ' ? 'space' : key);
  return parts.join('+');
}

function isEditableTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  if (!element) return false;
  const tag = element.tagName;
  return (
    tag === 'INPUT' ||
    tag === 'TEXTAREA' ||
    tag === 'SELECT' ||
    element.isContentEditable === true
  );
}

export function useHotkeys(hotkeys: Hotkey[]): void {
  function onKeydown(event: KeyboardEvent): void {
    const combo = normalize(event);
    const inInput = isEditableTarget(event.target);

    for (const hotkey of hotkeys) {
      if (hotkey.combo !== combo) continue;
      if (inInput && !hotkey.allowInInput) return;
      event.preventDefault();
      hotkey.handler();
      return;
    }
  }

  onMounted(() => window.addEventListener('keydown', onKeydown));
  onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown));
}

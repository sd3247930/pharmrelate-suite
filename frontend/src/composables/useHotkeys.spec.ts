/**
 * 快捷键测试。

 * 重点不是"能不能触发"，而是"什么时候**不该**触发"：
 * 操作员正在输入框里敲条码时，页面不该抢走按键。
 */

import { mount } from '@vue/test-utils';
import { defineComponent } from 'vue';
import { describe, expect, it, vi } from 'vitest';

import { useHotkeys } from './useHotkeys';

function mountWithHotkeys(hotkeys: Parameters<typeof useHotkeys>[0]) {
  const Probe = defineComponent({
    template: '<div><input id="field" /><button id="btn">按钮</button></div>',
    setup() {
      useHotkeys(hotkeys);
    },
  });
  return mount(Probe, { attachTo: document.body });
}

function press(key: string, options: KeyboardEventInit = {}, target?: HTMLElement) {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...options });
  (target ?? window).dispatchEvent(event);
  return event;
}

describe('useHotkeys', () => {
  it('Ctrl+Z 触发撤销', () => {
    const handler = vi.fn();
    mountWithHotkeys([{ combo: 'ctrl+z', handler }]);
    press('z', { ctrlKey: true });
    expect(handler).toHaveBeenCalledOnce();
  });

  it('Ctrl+Shift+Z 与 Ctrl+Z 是两个不同的键', () => {
    const undo = vi.fn();
    const redo = vi.fn();
    mountWithHotkeys([
      { combo: 'ctrl+z', handler: undo },
      { combo: 'ctrl+shift+z', handler: redo },
    ]);

    press('z', { ctrlKey: true, shiftKey: true });
    expect(redo).toHaveBeenCalledOnce();
    expect(undo).not.toHaveBeenCalled();
  });

  it('F5 触发刷新，并阻止浏览器默认刷新', () => {
    const handler = vi.fn();
    mountWithHotkeys([{ combo: 'f5', handler }]);
    const event = press('F5');
    expect(handler).toHaveBeenCalledOnce();
    expect(event.defaultPrevented).toBe(true);
  });

  it('在输入框里按键时不触发（不抢操作员的键盘）', () => {
    const handler = vi.fn();
    const wrapper = mountWithHotkeys([{ combo: 'ctrl+z', handler }]);
    const input = wrapper.find('#field').element;
    press('z', { ctrlKey: true }, input as HTMLElement);
    expect(handler).not.toHaveBeenCalled();
  });

  it('allowInInput 为真时在输入框里也可以触发', () => {
    const handler = vi.fn();
    const wrapper = mountWithHotkeys([
      { combo: 'escape', handler, allowInInput: true },
    ]);
    const input = wrapper.find('#field').element;
    press('Escape', {}, input as HTMLElement);
    expect(handler).toHaveBeenCalledOnce();
  });

  it('未注册的组合键不触发任何动作', () => {
    const handler = vi.fn();
    mountWithHotkeys([{ combo: 'ctrl+z', handler }]);
    press('x', { ctrlKey: true });
    expect(handler).not.toHaveBeenCalled();
  });
});

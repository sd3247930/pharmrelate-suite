<script setup lang="ts">
import { xml } from '@codemirror/lang-xml';
import { EditorState } from '@codemirror/state';
import { EditorView, lineNumbers } from '@codemirror/view';
import { basicSetup } from 'codemirror';
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';

/**
 * XML 只读查看器（CodeMirror 6）。

 * 为什么不用 textarea：12400 条 Code 的 XML 有几十万字符，textarea 会整块排版，
 * 长文本直接卡顿；CodeMirror 只渲染视口内的行。
 * 同时也是"原样展示"的要求——不给 XML 做任何自动格式化，
 * 否则展示的内容与导出的文件就不是同一份了。
 */
const props = withDefaults(
  defineProps<{
    value: string;
    height?: number;
    /** 只读是默认；保留开关便于将来做手工编辑。 */
    readonly?: boolean;
  }>(),
  { height: 420, readonly: true },
);

const host = ref<HTMLElement | null>(null);
let view: EditorView | null = null;

function createView(): void {
  if (!host.value) return;
  view = new EditorView({
    state: EditorState.create({
      doc: props.value,
      extensions: [
        basicSetup,
        lineNumbers(),
        xml(),
        EditorView.editable.of(!props.readonly),
        EditorState.readOnly.of(props.readonly),
        EditorView.theme({
          '&': { fontSize: '12px', height: `${props.height}px` },
          '.cm-scroller': { fontFamily: 'var(--font-mono)' },
          '.cm-gutters': {
            backgroundColor: 'var(--color-surface-alt)',
            borderRight: '1px solid var(--color-border)',
          },
          '&.cm-focused': { outline: 'none' },
        }),
      ],
    }),
    parent: host.value,
  });
}

function destroyView(): void {
  view?.destroy();
  view = null;
}

onMounted(createView);
onBeforeUnmount(destroyView);

// 内容变化时整体替换文档：XML 是"要么全对要么全错"的东西，
// 做增量 diff 只会引入不一致的可能。
watch(
  () => props.value,
  (next) => {
    if (!view) return;
    view.dispatch({
      changes: { from: 0, to: view.state.doc.length, insert: next },
    });
  },
);
</script>

<template>
  <div ref="host" class="xml-viewer" role="region" aria-label="XML 预览" />
</template>

<style scoped>
.xml-viewer {
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}
</style>

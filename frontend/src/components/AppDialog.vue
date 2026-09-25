<script setup lang="ts">
import { X } from 'lucide-vue-next';
import { onBeforeUnmount, ref, watch } from 'vue';

import AppButton from './AppButton.vue';

/**
 * 弹窗规范：
 *   - 只用于删除 / 作废 / 锁定 / 解锁 / 提前结束 / 覆盖数据等需要二次确认的场景
 *   - 扫码过程中的粒子批量录入**不要**用弹窗，否则现场连续扫描会被反复打断
 *   - 危险操作确认按钮单独分区，不与主按钮贴在一起
 */
const props = withDefaults(
  defineProps<{
    modelValue: boolean;
    title: string;
    description?: string;
    confirmLabel?: string;
    cancelLabel?: string;
    tone?: 'normal' | 'danger';
    busy?: boolean;
    hideConfirm?: boolean;
  }>(),
  {
    description: '',
    confirmLabel: '确认',
    cancelLabel: '取消',
    tone: 'normal',
    busy: false,
    hideConfirm: false,
  },
);

const emit = defineEmits<{ 'update:modelValue': [value: boolean]; confirm: [] }>();

const panel = ref<HTMLElement | null>(null);

function close(): void {
  emit('update:modelValue', false);
}

function onKeydown(event: KeyboardEvent): void {
  // Esc 关闭弹窗：现场人员不必去找关闭按钮
  if (event.key === 'Escape') close();
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      window.addEventListener('keydown', onKeydown);
      requestAnimationFrame(() => panel.value?.focus());
    } else {
      window.removeEventListener('keydown', onKeydown);
    }
  },
);

onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown));
</script>

<template>
  <Transition name="app-dialog">
    <div v-if="modelValue" class="app-dialog__backdrop" @click.self="close">
      <div
        ref="panel"
        class="app-dialog"
        role="dialog"
        aria-modal="true"
        :aria-label="title"
        tabindex="-1"
      >
        <header class="app-dialog__header">
          <h2 class="app-dialog__title">{{ title }}</h2>
          <button class="app-dialog__close" type="button" aria-label="关闭弹窗" @click="close">
            <X :size="18" aria-hidden="true" />
          </button>
        </header>

        <p v-if="description" class="app-dialog__description">{{ description }}</p>
        <div v-if="$slots.default" class="app-dialog__body"><slot /></div>

        <footer class="app-dialog__footer" :class="{ 'app-dialog__footer--danger': tone === 'danger' }">
          <AppButton variant="secondary" :disabled="busy" @click="close">{{ cancelLabel }}</AppButton>
          <AppButton
            v-if="!hideConfirm"
            :variant="tone === 'danger' ? 'danger' : 'primary'"
            :loading="busy"
            @click="emit('confirm')"
          >
            {{ confirmLabel }}
          </AppButton>
        </footer>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.app-dialog__backdrop {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  padding: var(--space-5);
  background: rgb(16 26 34 / 42%);
}

.app-dialog {
  width: min(560px, 100%);
  max-height: 86vh;
  overflow: auto;
  padding: var(--space-5);
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
}

.app-dialog__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}

.app-dialog__title {
  font-size: var(--text-xl);
}

.app-dialog__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  color: var(--color-text-muted);
  background: transparent;
  border: 0;
  border-radius: var(--radius-md);
  cursor: pointer;
}

.app-dialog__close:hover {
  background: var(--color-neutral-soft);
}

.app-dialog__description {
  margin-top: var(--space-3);
  color: var(--color-text-muted);
}

.app-dialog__body {
  margin-top: var(--space-4);
}

.app-dialog__footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  margin-top: var(--space-5);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

/* 危险操作单独分区：与普通确认按钮拉开距离，避免误触 */
.app-dialog__footer--danger {
  justify-content: space-between;
}

.app-dialog-enter-active,
.app-dialog-leave-active {
  transition: opacity var(--duration-normal) var(--ease-out);
}

.app-dialog-enter-from,
.app-dialog-leave-to {
  opacity: 0;
}
</style>

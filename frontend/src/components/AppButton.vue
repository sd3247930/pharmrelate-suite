<script setup lang="ts">
import { Loader2 } from 'lucide-vue-next';
import { computed } from 'vue';

/**
 * 按钮层级规范：
 *   primary   每页最多一个主 CTA
 *   secondary 次要动作
 *   ghost     低优先级
 *   danger    危险动作，视觉上必须与业务按钮明显拉开
 */
const props = withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
    size?: 'md' | 'lg';
    loading?: boolean;
    disabled?: boolean;
    block?: boolean;
    type?: 'button' | 'submit';
  }>(),
  {
    variant: 'secondary',
    size: 'md',
    loading: false,
    disabled: false,
    block: false,
    type: 'button',
  },
);

const classes = computed(() => [
  'app-button',
  `app-button--${props.variant}`,
  `app-button--${props.size}`,
  { 'app-button--block': props.block },
]);
</script>

<template>
  <button :class="classes" :type="type" :disabled="disabled || loading" :aria-busy="loading">
    <Loader2 v-if="loading" class="app-button__spinner" :size="16" aria-hidden="true" />
    <slot v-else name="icon" />
    <span class="app-button__label"><slot /></span>
  </button>
</template>

<style scoped>
.app-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-height: var(--touch-target);
  padding: 0 var(--space-4);
  font-size: var(--text-base);
  font-weight: var(--weight-medium);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition:
    background-color var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out);
}

.app-button--lg {
  min-height: 48px;
  padding: 0 var(--space-5);
  font-size: var(--text-lg);
}

.app-button--block {
  width: 100%;
}

.app-button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.app-button--primary {
  color: var(--color-text-inverse);
  background: var(--color-primary);
  border-color: var(--color-primary);
}

.app-button--primary:hover:not(:disabled) {
  background: var(--color-primary-strong);
  border-color: var(--color-primary-strong);
}

.app-button--secondary {
  color: var(--color-text);
  background: var(--color-surface);
  border-color: var(--color-border-strong);
}

.app-button--secondary:hover:not(:disabled) {
  background: var(--color-surface-alt);
}

.app-button--ghost {
  color: var(--color-text-muted);
  background: transparent;
}

.app-button--ghost:hover:not(:disabled) {
  color: var(--color-text);
  background: var(--color-neutral-soft);
}

/* 危险动作：实心红底 + 边框，与普通业务按钮完全不同层级 */
.app-button--danger {
  color: var(--color-text-inverse);
  background: var(--color-danger);
  border-color: var(--color-danger);
}

.app-button--danger:hover:not(:disabled) {
  background: #9a1616;
  border-color: #9a1616;
}

.app-button__spinner {
  animation: app-button-spin 900ms linear infinite;
}

@keyframes app-button-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>

<script setup lang="ts">
import { computed } from 'vue';

const props = withDefaults(
  defineProps<{
    value: number;
    max?: number;
    label?: string;
    showPercent?: boolean;
    tone?: 'normal' | 'warning' | 'danger' | 'success';
  }>(),
  { max: 100, label: '', showPercent: true, tone: 'normal' },
);

const percent = computed(() => {
  if (props.max <= 0) return 0;
  return Math.min(100, Math.max(0, (props.value / props.max) * 100));
});

const display = computed(() => `${Math.round(percent.value * 10) / 10}%`);
</script>

<template>
  <div class="app-progress">
    <div v-if="label || showPercent" class="app-progress__head">
      <span v-if="label" class="app-progress__label">{{ label }}</span>
      <span v-if="showPercent" class="app-progress__percent code-text">{{ display }}</span>
    </div>
    <!-- 进度条只是辅助，具体数值始终以文字呈现 -->
    <div
      class="app-progress__track"
      role="progressbar"
      :aria-valuenow="Math.round(percent)"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-label="label || '进度'"
    >
      <div class="app-progress__bar" :class="`app-progress__bar--${tone}`" :style="{ width: `${percent}%` }" />
    </div>
  </div>
</template>

<style scoped>
.app-progress {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.app-progress__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  font-size: var(--text-sm);
}

.app-progress__label {
  color: var(--color-text-muted);
}

.app-progress__percent {
  font-weight: var(--weight-semibold);
}

.app-progress__track {
  height: 8px;
  overflow: hidden;
  background: var(--color-surface-sunken);
  border-radius: var(--radius-pill);
}

.app-progress__bar {
  height: 100%;
  transition: width var(--duration-normal) var(--ease-out);
}

.app-progress__bar--normal {
  background: var(--color-primary);
}

.app-progress__bar--success {
  background: var(--color-success);
}

.app-progress__bar--warning {
  background: var(--color-warning);
}

.app-progress__bar--danger {
  background: var(--color-danger);
}
</style>

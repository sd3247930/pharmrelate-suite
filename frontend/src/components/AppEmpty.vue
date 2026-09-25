<script setup lang="ts">
import { Inbox, type LucideIcon } from 'lucide-vue-next';

/**
 * 空状态。每个列表页都必须有，不能只显示空白。
 * 空状态同时承担"下一步该做什么"的引导职责。
 */
withDefaults(
  defineProps<{
    title: string;
    description?: string;
    icon?: LucideIcon;
  }>(),
  { description: '', icon: undefined },
);
</script>

<template>
  <div class="app-empty">
    <component :is="icon ?? Inbox" :size="32" class="app-empty__icon" aria-hidden="true" />
    <p class="app-empty__title">{{ title }}</p>
    <p v-if="description" class="app-empty__description">{{ description }}</p>
    <div v-if="$slots.default" class="app-empty__action"><slot /></div>
  </div>
</template>

<style scoped>
.app-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-7) var(--space-5);
  text-align: center;
}

.app-empty__icon {
  color: var(--color-text-subtle);
}

.app-empty__title {
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
}

.app-empty__description {
  max-width: 46ch;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.app-empty__action {
  margin-top: var(--space-2);
}
</style>

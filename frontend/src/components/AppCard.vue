<script setup lang="ts">
withDefaults(
  defineProps<{
    title?: string;
    subtitle?: string;
    padding?: 'md' | 'lg' | 'none';
  }>(),
  { title: '', subtitle: '', padding: 'lg' },
);
</script>

<template>
  <section class="app-card" :class="`app-card--padding-${padding}`">
    <header v-if="title || $slots.actions" class="app-card__header">
      <div>
        <h3 v-if="title" class="app-card__title">{{ title }}</h3>
        <p v-if="subtitle" class="app-card__subtitle">{{ subtitle }}</p>
      </div>
      <div v-if="$slots.actions" class="app-card__actions"><slot name="actions" /></div>
    </header>
    <slot />
    <footer v-if="$slots.footer" class="app-card__footer"><slot name="footer" /></footer>
  </section>
</template>

<style scoped>
.app-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}

.app-card--padding-md {
  padding: var(--space-4);
}

.app-card--padding-lg {
  padding: var(--space-5);
}

.app-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.app-card__title {
  font-size: var(--text-lg);
}

.app-card__subtitle {
  margin-top: var(--space-1);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.app-card__actions {
  display: flex;
  gap: var(--space-2);
  flex-shrink: 0;
}

.app-card__footer {
  display: flex;
  gap: var(--space-3);
  justify-content: flex-end;
  margin-top: var(--space-5);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}
</style>

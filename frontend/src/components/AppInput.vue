<script setup lang="ts">
import { AlertTriangle } from 'lucide-vue-next';
import { computed, useId } from 'vue';

const props = withDefaults(
  defineProps<{
    modelValue: string | number;
    label?: string;
    type?: 'text' | 'date' | 'number';
    hint?: string;
    error?: string;
    placeholder?: string;
    min?: number;
    max?: number;
    required?: boolean;
    disabled?: boolean;
    readonly?: boolean;
    monospace?: boolean;
  }>(),
  {
    label: '',
    type: 'text',
    hint: '',
    error: '',
    placeholder: '',
    min: undefined,
    max: undefined,
    required: false,
    disabled: false,
    readonly: false,
    monospace: false,
  },
);

const emit = defineEmits<{ 'update:modelValue': [value: string | number] }>();

const fieldId = useId();
const errorId = `${fieldId}-error`;
const hintId = `${fieldId}-hint`;

const describedBy = computed(() => {
  const ids = [];
  if (props.hint) ids.push(hintId);
  if (props.error) ids.push(errorId);
  return ids.length ? ids.join(' ') : undefined;
});

function onInput(event: Event): void {
  const target = event.target as HTMLInputElement;
  if (props.type === 'number') {
    emit('update:modelValue', target.value === '' ? '' : Number(target.value));
    return;
  }
  emit('update:modelValue', target.value);
}
</script>

<template>
  <div class="app-input" :class="{ 'app-input--error': !!error, 'app-input--disabled': disabled }">
    <label v-if="label" class="app-input__label" :for="fieldId">
      {{ label }}
      <span v-if="required" class="app-input__required" aria-hidden="true">*</span>
      <span v-if="required" class="sr-only">必填</span>
    </label>
    <div class="app-input__control">
      <span v-if="$slots.prefix" class="app-input__affix"><slot name="prefix" /></span>
      <input
        :id="fieldId"
        :type="type"
        :value="modelValue"
        :placeholder="placeholder"
        :min="min"
        :max="max"
        :required="required"
        :disabled="disabled"
        :readonly="readonly"
        :aria-invalid="!!error"
        :aria-describedby="describedBy"
        :class="{ 'code-text': monospace }"
        @input="onInput"
      />
      <span v-if="$slots.suffix" class="app-input__affix"><slot name="suffix" /></span>
    </div>
    <p v-if="hint && !error" :id="hintId" class="app-input__hint">{{ hint }}</p>
    <!-- 错误信息紧贴出错的字段，而不是汇总到页面顶部 -->
    <p v-if="error" :id="errorId" class="app-input__error" role="alert">
      <AlertTriangle :size="14" aria-hidden="true" />
      <span>{{ error }}</span>
    </p>
  </div>
</template>

<style scoped>
.app-input {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.app-input__label {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text-muted);
}

.app-input__required {
  color: var(--color-danger);
}

.app-input__control {
  display: flex;
  align-items: center;
  min-height: var(--touch-target);
  background: var(--color-surface);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  transition: border-color var(--duration-fast) var(--ease-out);
}

.app-input__control:focus-within {
  border-color: var(--color-primary);
  box-shadow: var(--focus-ring);
}

.app-input--error .app-input__control {
  border-color: var(--color-danger);
}

.app-input--disabled .app-input__control {
  background: var(--color-surface-sunken);
}

.app-input__control input {
  flex: 1;
  min-width: 0;
  padding: 0 var(--space-3);
  font: inherit;
  color: inherit;
  background: transparent;
  border: 0;
  outline: none;
}

.app-input__control input:disabled {
  color: var(--color-text-muted);
  cursor: not-allowed;
}

.app-input__affix {
  display: inline-flex;
  align-items: center;
  padding: 0 var(--space-3);
  color: var(--color-text-muted);
}

.app-input__hint {
  font-size: var(--text-xs);
  color: var(--color-text-subtle);
}

.app-input__error {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-danger);
}
</style>

<script setup lang="ts">
import { FilePlus2, FolderOpen, PencilLine } from 'lucide-vue-next';

import AppDialog from './AppDialog.vue';
import AppStatusBadge from './AppStatusBadge.vue';
import type { BatchNoConflict } from '../types/batch';

/**
 * 重复批号三选一（V1.1 8.4）。
 *
 * 关键交互约束：不能只报「批号重复」然后把操作员挡死。必须给出三条明确出路，
 * 并且把已有批次的关键信息摆出来，让人能判断该打开旧的还是建新版本。
 */
const props = defineProps<{
  modelValue: boolean;
  conflict: BatchNoConflict | null;
  busy?: boolean;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: boolean];
  openExisting: [];
  createNewVersion: [];
  cancel: [];
}>();

function toneOf(status: string): string {
  return status || 'draft';
}
</script>

<template>
  <AppDialog
    :model-value="modelValue"
    title="检测到批号已存在"
    :busy="busy"
    cancel-label="关闭"
    hide-confirm
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template v-if="conflict">
      <dl class="conflict__facts">
        <div>
          <dt>批号</dt>
          <dd class="code-text">{{ conflict.existing.batchNo }}</dd>
        </div>
        <div>
          <dt>当前状态</dt>
          <dd><AppStatusBadge :tone="toneOf(conflict.existing.status) as never" /></dd>
        </div>
        <div>
          <dt>罐 / 粒子</dt>
          <dd class="code-text">
            {{ conflict.existing.canCount }} 罐 / {{ conflict.existing.actualParticleTotal }} 粒
          </dd>
        </div>
        <div>
          <dt>最后更新</dt>
          <dd class="code-text">{{ conflict.existing.updatedAt }}</dd>
        </div>
      </dl>

      <p class="conflict__hint">请选择下一步：</p>

      <div class="conflict__options">
        <button class="conflict__option" type="button" @click="emit('openExisting')">
          <FolderOpen :size="20" aria-hidden="true" />
          <span>
            <strong>打开已有批次</strong>
            <em>继续编辑或查看这个批次</em>
          </span>
        </button>

        <button class="conflict__option" type="button" @click="emit('createNewVersion')">
          <FilePlus2 :size="20" aria-hidden="true" />
          <span>
            <strong>创建新版本 {{ conflict.suggestedBatchNo }}</strong>
            <em>保留原批次，用新批号另存一份</em>
          </span>
        </button>

        <button class="conflict__option" type="button" @click="emit('cancel')">
          <PencilLine :size="20" aria-hidden="true" />
          <span>
            <strong>取消并返回修改</strong>
            <em>回到表单，自己换一个批号</em>
          </span>
        </button>
      </div>
    </template>
  </AppDialog>
</template>

<style scoped>
.conflict__facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--space-4);
  margin: 0;
  padding: var(--space-4);
  background: var(--color-surface-alt);
  border-radius: var(--radius-md);
}

.conflict__facts dt {
  font-size: var(--text-xs);
  color: var(--color-text-subtle);
}

.conflict__facts dd {
  margin: var(--space-1) 0 0;
  font-weight: var(--weight-medium);
}

.conflict__hint {
  margin-top: var(--space-5);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.conflict__options {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin-top: var(--space-3);
}

.conflict__option {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  min-height: 64px;
  padding: var(--space-3) var(--space-4);
  text-align: left;
  background: var(--color-surface);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out);
}

.conflict__option:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
}

.conflict__option span {
  display: flex;
  flex-direction: column;
}

.conflict__option em {
  font-size: var(--text-sm);
  font-style: normal;
  color: var(--color-text-muted);
}
</style>

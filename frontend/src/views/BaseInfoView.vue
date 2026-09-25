<script setup lang="ts">
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Info, Lock, Save } from 'lucide-vue-next';
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';

import AppBatchNoConflictDialog from '../components/AppBatchNoConflictDialog.vue';
import AppButton from '../components/AppButton.vue';
import AppCard from '../components/AppCard.vue';
import AppInput from '../components/AppInput.vue';
import AppStatusBadge from '../components/AppStatusBadge.vue';
import { useBatchStore } from '../stores/batch';
import { classifyCode, CODE_LENGTH, PACK_LAYER_BOX } from '../types/batch';

/**
 * 界面 1：基础信息。
 *
 * 固定参数不在主表单里展开成输入框，而是折叠在只读区 —— 它们由程序写死，
 * 让操作员看到可编辑的输入框只会制造误操作机会。
 */
const router = useRouter();
const batch = useBatchStore();

const fixedOpen = ref(false);
const conflictOpen = computed({
  get: () => batch.conflict !== null,
  set: (value: boolean) => {
    if (!value) batch.dismissConflict();
  },
});

const FIXED = [
  { label: '产品代码', value: '9999999' },
  { label: '子类型编号', value: '9500000001' },
  { label: '级联', value: '1:5:2500' },
  { label: '包装规格', value: '粒1粒' },
  { label: '备注 comment', value: '0' },
  { label: '状态标志 flag', value: '2' },
  { label: '车间', value: '一号车间' },
  { label: '生产线', value: '一号生产线' },
  { label: '负责人', value: '操作员甲' },
  { label: '许可证 License', value: '1001123' },
  { label: 'Schema', value: '关联关系XML Schema-3.0.xsd' },
  { label: '事件版本', value: '3.0 · RelationCreate' },
];

const batchNoError = computed(() => {
  const value = batch.batchNo.trim();
  if (!value) return '';
  if (!/^[0-9A-Za-z-]{6,20}$/.test(value)) return '批号只支持数字与英文字母，长度 6～20 位。';
  return '';
});

const dateError = computed(() => {
  if (!batch.madeDate || !batch.validateDate) return '';
  return batch.validateDate <= batch.madeDate ? '有效期必须晚于生产日期。' : '';
});

const boxCodeError = computed(() => {
  const value = batch.boxCode.trim();
  if (!value) return '';
  if (value.length !== CODE_LENGTH || !/^\d+$/.test(value)) {
    return `箱号必须是 ${CODE_LENGTH} 位数字，当前为 ${value.length} 位。`;
  }
  return classifyCode(value) === PACK_LAYER_BOX ? '' : '该条码不是箱号（箱号以 8021761 开头）。';
});

const canContinue = computed(
  () => batch.batchNo.trim() && batch.madeDate && batch.validateDate && !batchNoError.value && !dateError.value,
);

function goNext(): void {
  if (!canContinue.value) return;
  router.push('/package-structure');
}

async function saveDraft(): Promise<void> {
  const ok = await batch.saveDraft();
  if (ok) conflictOpen.value = false;
}

async function createNewVersion(): Promise<void> {
  await batch.saveDraft(true);
  conflictOpen.value = false;
}

async function openExisting(): Promise<void> {
  const id = batch.conflict?.existing.id;
  if (!id) return;
  await batch.openExisting(id);
  conflictOpen.value = false;
}
</script>

<template>
  <div class="base-info">
    <AppCard title="基础信息" subtitle="三项由操作员填写，其余参数由程序固定，不随包装结构变化。">
      <template #actions>
        <AppStatusBadge
          :tone="(batch.status as never)"
          :label="batch.statusLabel"
          :detail="batch.editable ? undefined : '只读'"
        />
      </template>

      <p v-if="!batch.editable" class="base-info__locked" role="status">
        <Lock :size="16" aria-hidden="true" />
        当前状态为「{{ batch.statusLabel }}」，业务数据只读。如需修改，请先由管理员解锁。
      </p>

      <p v-if="batch.notice" class="base-info__notice" role="status">
        <CheckCircle2 :size="16" aria-hidden="true" />
        {{ batch.notice }}
      </p>
      <p v-if="batch.errorMessage" class="base-info__error" role="alert">
        <AlertTriangle :size="16" aria-hidden="true" />
        {{ batch.errorMessage }}
      </p>

      <div class="base-info__form">
        <AppInput
          v-model="batch.batchNo"
          label="批号"
          placeholder="例如 20260901"
          required
          monospace
          :readonly="!batch.editable"
          :error="batchNoError"
          hint="数字与英文字母，6～20 位。"
        />
        <AppInput
          v-model="batch.madeDate"
          label="生产日期"
          type="date"
          required
          :readonly="!batch.editable"
        />
        <AppInput
          v-model="batch.validateDate"
          label="有效期"
          type="date"
          required
          :readonly="!batch.editable"
          :error="dateError"
        />
        <AppInput
          v-model="batch.boxCode"
          label="箱号"
          placeholder="扫描或输入 20 位箱号"
          monospace
          :readonly="!batch.editable"
          :error="boxCodeError"
          hint="箱号以 8021761 开头，定长 20 位。"
        />
      </div>

      <template #footer>
        <AppButton variant="ghost" @click="batch.reset()">重置</AppButton>
        <AppButton
          variant="secondary"
          :disabled="!batch.editable"
          :loading="batch.busy"
          @click="saveDraft"
        >
          <template #icon><Save :size="16" aria-hidden="true" /></template>
          {{ batch.isNew ? '保存草稿' : '保存修改' }}
        </AppButton>
        <AppButton variant="primary" :disabled="!canContinue || !batch.editable" @click="goNext">
          下一步：设置包装结构
          <template #icon><ChevronRight :size="16" aria-hidden="true" /></template>
        </AppButton>
      </template>
    </AppCard>

    <AppBatchNoConflictDialog
      v-model="conflictOpen"
      :conflict="batch.conflict"
      :busy="batch.busy"
      @open-existing="openExisting"
      @create-new-version="createNewVersion"
      @cancel="batch.dismissConflict()"
    />

    <AppCard padding="none">
      <button class="base-info__toggle" type="button" :aria-expanded="fixedOpen" @click="fixedOpen = !fixedOpen">
        <component :is="fixedOpen ? ChevronDown : ChevronRight" :size="16" aria-hidden="true" />
        <span>系统固定参数</span>
        <em>只读 · 由程序写死</em>
      </button>

      <div v-if="fixedOpen" class="base-info__fixed">
        <dl>
          <div v-for="item in FIXED" :key="item.label">
            <dt>{{ item.label }}</dt>
            <dd class="code-text">{{ item.value }}</dd>
          </div>
        </dl>
        <p class="base-info__note">
          <Info :size="15" aria-hidden="true" />
          注意：<code class="code-text">cascade="1:5:2500"</code> 是固定字面量。实测 1 罐 400 粒的批次
          cascade 依然是 1:5:2500，因此它不随实际罐数或粒子数变化。
        </p>
      </div>
    </AppCard>
  </div>
</template>

<style scoped>
.base-info {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.base-info__form {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--space-5);
  margin-top: var(--space-4);
}

.base-info__locked {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  background: var(--color-surface-sunken);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
}

.base-info__notice {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-3);
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-success);
  background: var(--color-success-soft);
  border: 1px solid var(--color-success-border);
  border-radius: var(--radius-md);
}

.base-info__error {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-3);
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-danger);
  background: var(--color-danger-soft);
  border: 1px solid var(--color-danger-border);
  border-radius: var(--radius-md);
}

.base-info__toggle {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  min-height: 52px;
  padding: 0 var(--space-5);
  font-size: var(--text-base);
  font-weight: var(--weight-medium);
  text-align: left;
  background: transparent;
  border: 0;
  cursor: pointer;
}

.base-info__toggle em {
  margin-left: auto;
  font-size: var(--text-xs);
  font-style: normal;
  color: var(--color-text-subtle);
}

.base-info__fixed {
  padding: 0 var(--space-5) var(--space-5);
  border-top: 1px solid var(--color-border);
}

.base-info__fixed dl {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--space-4);
  margin: var(--space-4) 0 0;
}

.base-info__fixed dt {
  font-size: var(--text-xs);
  color: var(--color-text-subtle);
}

.base-info__fixed dd {
  margin: var(--space-1) 0 0;
}

.base-info__note {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  margin-top: var(--space-5);
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-warning);
  background: var(--color-warning-soft);
  border: 1px solid var(--color-warning-border);
  border-radius: var(--radius-md);
}
</style>

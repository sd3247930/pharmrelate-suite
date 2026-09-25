<script setup lang="ts">
import { AlertTriangle, Box, ChevronRight, Cylinder, Minus, Plus } from 'lucide-vue-next';
import { computed } from 'vue';
import { useRouter } from 'vue-router';

import AppButton from '../components/AppButton.vue';
import AppCard from '../components/AppCard.vue';
import AppInput from '../components/AppInput.vue';
import AppProgress from '../components/AppProgress.vue';
import { useBatchStore } from '../stores/batch';
import {
  MAX_CANS,
  MAX_PARTICLES_PER_BATCH,
  MAX_PARTICLES_PER_CAN,
  MIN_CANS,
} from '../types/batch';

/**
 * 界面 2：包装结构。
 *
 * 罐数 1～5、每罐 1～2500 粒。超过单批次 12500 粒时**实时**提示，
 * 不等到点击下一步才报错。
 */
const router = useRouter();
const batch = useBatchStore();

const exceedCanLimit = computed(() => batch.cans.some((can) => can.plannedParticleCount > MAX_PARTICLES_PER_CAN));
const emptyCan = computed(() => batch.cans.some((can) => !can.plannedParticleCount || can.plannedParticleCount < 1));
const canContinue = computed(() => !batch.overBatchLimit && !exceedCanLimit && !emptyCan);

function stepCan(delta: number): void {
  batch.setCanCount(batch.canCount + delta);
}

function goNext(): void {
  if (!canContinue.value) return;
  router.push('/scanning');
}
</script>

<template>
  <div class="structure">
    <AppCard title="包装结构" subtitle="一级固定 1 箱；罐数 1～5；每罐粒子数 1～2500。">
      <div class="structure__box">
        <Box :size="18" aria-hidden="true" />
        <span>纸箱数</span>
        <strong class="code-text">1</strong>
        <em>固定，不可修改</em>
      </div>

      <div class="structure__counter">
        <span>罐数量</span>
        <div class="structure__stepper">
          <button
            type="button"
            aria-label="减少罐数"
            :disabled="batch.canCount <= MIN_CANS"
            @click="stepCan(-1)"
          >
            <Minus :size="16" aria-hidden="true" />
          </button>
          <output class="code-text" aria-live="polite">{{ batch.canCount }}</output>
          <button
            type="button"
            aria-label="增加罐数"
            :disabled="batch.canCount >= MAX_CANS"
            @click="stepCan(1)"
          >
            <Plus :size="16" aria-hidden="true" />
          </button>
        </div>
        <em>范围 {{ MIN_CANS }}～{{ MAX_CANS }}</em>
      </div>

      <ul class="structure__cans">
        <li v-for="(can, index) in batch.cans" :key="can.index">
          <div class="structure__can-head">
            <Cylinder :size="16" aria-hidden="true" />
            <span>罐 {{ can.index }}</span>
          </div>
          <AppInput
            v-model="can.plannedParticleCount"
            label="粒子数量"
            type="number"
            :min="1"
            :max="MAX_PARTICLES_PER_CAN"
            :error="
              can.plannedParticleCount > MAX_PARTICLES_PER_CAN
                ? `不得超过 ${MAX_PARTICLES_PER_CAN} 粒`
                : ''
            "
            @update:model-value="batch.clampParticles(index)"
          />
        </li>
      </ul>

      <div class="structure__total">
        <div>
          <span>总粒子数</span>
          <strong class="code-text">{{ batch.plannedParticleTotal.toLocaleString('en-US') }}</strong>
        </div>
        <AppProgress
          :value="batch.plannedParticleTotal"
          :max="MAX_PARTICLES_PER_BATCH"
          :tone="batch.overBatchLimit ? 'danger' : 'normal'"
          label="占单批次上限"
        />
      </div>

      <p v-if="batch.overBatchLimit" class="structure__alert" role="alert">
        <AlertTriangle :size="16" aria-hidden="true" />
        已超过单批次上限：当前 {{ batch.plannedParticleTotal.toLocaleString('en-US') }} 粒，
        最大 {{ MAX_PARTICLES_PER_BATCH.toLocaleString('en-US') }} 粒，请拆分为多个批次。
      </p>

      <template #footer>
        <AppButton variant="secondary" @click="router.push('/base-info')">返回上一步</AppButton>
        <AppButton variant="primary" :disabled="!canContinue" @click="goNext">
          下一步：扫码采集
          <template #icon><ChevronRight :size="16" aria-hidden="true" /></template>
        </AppButton>
      </template>
    </AppCard>
  </div>
</template>

<style scoped>
.structure__box {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--color-surface-alt);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.structure__box strong {
  font-size: var(--text-lg);
}

.structure__box em {
  font-size: var(--text-sm);
  font-style: normal;
  color: var(--color-text-subtle);
}

.structure__counter {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-top: var(--space-5);
}

.structure__counter em {
  font-size: var(--text-sm);
  font-style: normal;
  color: var(--color-text-subtle);
}

.structure__stepper {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.structure__stepper button {
  display: grid;
  place-items: center;
  width: var(--touch-target);
  height: var(--touch-target);
  background: var(--color-surface);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  cursor: pointer;
}

.structure__stepper button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.structure__stepper output {
  min-width: 48px;
  font-size: var(--text-xl);
  font-weight: var(--weight-semibold);
  text-align: center;
}

.structure__cans {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--space-4);
  margin: var(--space-5) 0 0;
  padding: 0;
  list-style: none;
}

.structure__cans li {
  padding: var(--space-4);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.structure__can-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  font-weight: var(--weight-medium);
}

.structure__total {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  margin-top: var(--space-5);
  padding: var(--space-4);
  background: var(--color-surface-alt);
  border-radius: var(--radius-md);
}

.structure__total > div:first-child {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.structure__total span {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.structure__total strong {
  font-size: var(--text-2xl);
}

.structure__total :deep(.app-progress) {
  flex: 1;
}

.structure__alert {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-4);
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-danger);
  background: var(--color-danger-soft);
  border: 1px solid var(--color-danger-border);
  border-radius: var(--radius-md);
}
</style>

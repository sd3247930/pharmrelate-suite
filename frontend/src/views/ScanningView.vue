<script setup lang="ts">
import { Camera, CheckCircle2, CircleAlert, ScanLine, TriangleAlert } from 'lucide-vue-next';
import { computed, ref } from 'vue';

import AppButton from '../components/AppButton.vue';
import AppCard from '../components/AppCard.vue';
import AppInput from '../components/AppInput.vue';
import AppStatusBadge from '../components/AppStatusBadge.vue';
import {
  CODE_LENGTH,
  LAYER_LABELS,
  MAX_CANS,
  MAX_PARTICLES_PER_BATCH,
  classifyCode,
} from '../types/batch';

/**
 * 界面 3：扫码采集。
 *
 * 阶段 1 只落地"状态机骨架 + 条码层级校验器"；摄像头取流、多码识别、
 * 虚拟槽位网格、撤销重做在阶段 3 实现。
 *
 * 层级校验器是**真实可用**的功能而不是演示占位：现场遇到可疑条码时，
 * 可以直接粘进来判断它属于哪一层。
 */
const probe = ref('');

const STATES = [
  'IDLE 待机',
  'SCANNING_BOX 拍箱号',
  'BOX_CONFIRM 箱号确认',
  'SCANNING_CAN 拍罐号',
  'CAN_CONFIRM 罐号确认',
  'SCANNING_PARTICLE 拍粒子',
  'CAN_COMPLETE_CONFIRM 本罐完成确认',
  'NEXT_CAN_CONFIRM 下一罐确认',
  'PENDING_REVIEW 待核对',
  'VERIFIED 已核对',
  'EXPORT 导出',
];

const probeResult = computed(() => {
  const value = probe.value.trim();
  if (!value) return null;
  if (value.length !== CODE_LENGTH || !/^\d+$/.test(value)) {
    return {
      ok: false,
      title: '不是合法条码',
      detail: `条码必须是 ${CODE_LENGTH} 位 ASCII 数字，当前为 ${value.length} 位。`,
    };
  }
  const layer = classifyCode(value);
  if (layer === null) {
    return {
      ok: false,
      title: '前缀不在白名单内',
      detail: '已知前缀：箱 8021761 / 罐 8021762 / 粒子 8206233。',
    };
  }
  return {
    ok: true,
    title: `这是${LAYER_LABELS[layer]}`,
    detail: `packLayer=${layer}，前缀 ${value.slice(0, 7)} 命中白名单。`,
  };
});
</script>

<template>
  <div class="scanning">
    <AppCard title="扫码采集" subtitle="阶段 3 实现摄像头取流与多码识别；此处先固定状态机与校验规则。">
      <template #actions>
        <AppStatusBadge tone="draft" label="未开始采集" />
      </template>

      <div class="scanning__stage">
        <Camera :size="40" aria-hidden="true" />
        <p class="scanning__stage-title">相机区域（阶段 3 接入 USB 摄像头）</p>
        <p class="scanning__stage-detail">
          现场输入形态已确认：一张标签纸 2 行 × 3 列共 6 枚粒子码，纸面反光、背景为木纹桌面，
          因此识别层必须支持单帧多码与抗反光预处理。
        </p>
      </div>
    </AppCard>

    <AppCard title="条码层级校验器" subtitle="真实可用：粘入条码即可判断它属于箱、罐还是粒子。">
      <AppInput
        v-model="probe"
        label="条码"
        placeholder="粘贴 20 位条码"
        monospace
        hint="用于在扫入前拦截「把粒子码当罐号扫」这类错层操作。"
      />

      <p v-if="probeResult" class="scanning__probe" :class="probeResult.ok ? 'is-ok' : 'is-bad'" role="status">
        <component :is="probeResult.ok ? CheckCircle2 : TriangleAlert" :size="18" aria-hidden="true" />
        <span>
          <strong>{{ probeResult.title }}</strong>
          <em>{{ probeResult.detail }}</em>
        </span>
      </p>
    </AppCard>

    <div class="scanning__grid">
      <AppCard title="扫码状态机" subtitle="阶段 3 按此流程实现，不用大量 if/else 隐式控制。">
        <ol class="scanning__states">
          <li v-for="(state, index) in STATES" :key="state">
            <span class="code-text">{{ String(index + 1).padStart(2, '0') }}</span>
            <span>{{ state.split(' ')[0] }}</span>
            <em>{{ state.split(' ')[1] }}</em>
          </li>
        </ol>
        <p class="scanning__note">
          <CircleAlert :size="15" aria-hidden="true" />
          异常状态（SCAN_FAILED / MULTI_CODE_DETECTED / DUPLICATE_CODE / SLOT_CONFLICT）
          独立处理，不混入主流程。
        </p>
      </AppCard>

      <AppCard title="已固定的规则" subtitle="来自两个真实 XML 基准与现场照片的实测结论。">
        <ul class="scanning__rules">
          <li>箱号、罐号必须严格单码；识别到 ≥2 个条码即报警并要求重拍。</li>
          <li>粒子支持批量多码，本次识别结果必须先给出「有效 / 重复 / 异常」三元统计再一次性入格。</li>
          <li>任何条码写入前执行全局去重，重复条码必须指出它已绑定的位置。</li>
          <li>粒子顺序保持采集原始顺序，导出时禁止排序。</li>
          <li>罐数上限 {{ MAX_CANS }}，单批次粒子上限 {{ MAX_PARTICLES_PER_BATCH.toLocaleString('en-US') }}。</li>
          <li>缺漏槽位默认禁止导出；「提前结束」做成正常按钮并记录原因与操作人。</li>
        </ul>
        <template #footer>
          <AppButton variant="ghost" disabled>
            <template #icon><ScanLine :size="16" aria-hidden="true" /></template>
            开始扫描（阶段 3）
          </AppButton>
        </template>
      </AppCard>
    </div>
  </div>
</template>

<style scoped>
.scanning {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.scanning__stage {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-7) var(--space-5);
  color: var(--color-text-muted);
  text-align: center;
  background: var(--color-surface-alt);
  border: 2px dashed var(--color-border-strong);
  border-radius: var(--radius-lg);
}

.scanning__stage-title {
  font-size: var(--text-lg);
  font-weight: var(--weight-medium);
  color: var(--color-text);
}

.scanning__stage-detail {
  max-width: 62ch;
  font-size: var(--text-sm);
}

.scanning__probe {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  margin-top: var(--space-4);
  padding: var(--space-3) var(--space-4);
  border: 1px solid;
  border-radius: var(--radius-md);
}

.scanning__probe span {
  display: flex;
  flex-direction: column;
}

.scanning__probe em {
  font-size: var(--text-sm);
  font-style: normal;
  color: var(--color-text-muted);
}

.scanning__probe.is-ok {
  color: var(--color-success);
  background: var(--color-success-soft);
  border-color: var(--color-success-border);
}

.scanning__probe.is-bad {
  color: var(--color-danger);
  background: var(--color-danger-soft);
  border-color: var(--color-danger-border);
}

.scanning__grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--space-5);
}

@media (max-width: 1100px) {
  .scanning__grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

.scanning__states {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
  counter-reset: none;
}

.scanning__states li {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
  background: var(--color-surface-alt);
  border-radius: var(--radius-sm);
}

.scanning__states li span:first-child {
  color: var(--color-text-subtle);
}

.scanning__states li em {
  margin-left: auto;
  font-style: normal;
  color: var(--color-text-muted);
}

.scanning__note {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-warning);
}

.scanning__rules {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin: 0;
  padding-left: var(--space-5);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}
</style>

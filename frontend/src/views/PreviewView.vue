<script setup lang="ts">
import {
  ArrowRight,
  CheckCircle2,
  Copy,
  Download,
  FileWarning,
  FlaskConical,
  Lock,
  LogOut,
  Save,
  TriangleAlert,
  Undo2,
} from 'lucide-vue-next';
import { computed, ref } from 'vue';

import AppDialog from '../components/AppDialog.vue';
import AppButton from '../components/AppButton.vue';
import AppCard from '../components/AppCard.vue';
import AppEmpty from '../components/AppEmpty.vue';
import AppInput from '../components/AppInput.vue';
import AppStatusBadge from '../components/AppStatusBadge.vue';
import { ApiError, api } from '../api/client';
import { useBatchStore } from '../stores/batch';

/**
 * 界面 4：预览与导出。
 *
 * 阶段 1 打通"批次数据 → 后端生成器 → XML 文本 → SHA-256"的完整链路，
 * 并支持一键载入真实基准文件反向验证字节级一致性。
 * XML 文件下载与 HTML 导出在阶段 4 实现。
 */
const batch = useBatchStore();

const loadingSample = ref(false);
const sampleMessage = ref('');
const copyState = ref('');

// 流转原因 / 解锁原因
const reasonDialogOpen = ref(false);
const pendingTarget = ref('');
const transitionReason = ref('');
const transitionOperator = ref('操作员甲');

// 提前结束签名
const earlyEndOpen = ref(false);
const earlyEndReason = ref('');
const earlyEndOperator = ref('操作员甲');
const earlyEndNote = ref('');

const OPERATORS = ['操作员甲', '操作员乙', '操作员丙', '操作员丁'];

const pendingTargetLabel = computed(
  () => batch.transitions.find((item) => item.target === pendingTarget.value)?.label ?? '',
);
const pendingNeedsReason = computed(
  () => batch.transitions.find((item) => item.target === pendingTarget.value)?.requiresReason ?? false,
);

const errorIssues = computed(() => batch.issues.filter((issue) => issue.severity === 'error'));
const warningIssues = computed(() => batch.issues.filter((issue) => issue.severity === 'warning'));

const xmlLines = computed(() => (batch.preview ? batch.preview.replace(/\n$/, '').split('\n') : []));

/** 预览里的 XML 是否与某个基准文件逐字符相同（用于页面上直接印证字节级一致）。 */
const matchesGolden = ref<string>('');

async function loadSample(name: string): Promise<void> {
  loadingSample.value = true;
  sampleMessage.value = '';
  matchesGolden.value = '';
  try {
    const xml = await api.goldenXml(name);
    batch.loadFromGoldenXml(xml);
    sampleMessage.value = `已从基准文件 ${name} 载入结构。`;
  } catch (error) {
    sampleMessage.value = error instanceof Error ? error.message : String(error);
  } finally {
    loadingSample.value = false;
  }
}

async function generate(): Promise<void> {
  matchesGolden.value = '';
  await batch.runPreview();
}

/** 生成后立刻与两个基准文件比对，把"字节级一致"变成界面上可见的事实。 */
async function verifyAgainstGolden(): Promise<void> {
  if (!batch.preview) return;
  const results: string[] = [];
  for (const name of ['1箱3罐.xml', '一箱一罐.xml']) {
    try {
      const goldenXml = await api.goldenXml(name);
      if (goldenXml === batch.preview) results.push(name);
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
    }
  }
  matchesGolden.value = results.length ? results.join('、') : 'none';
}

async function copyXml(): Promise<void> {
  if (!batch.preview) return;
  try {
    await navigator.clipboard.writeText(batch.preview);
    copyState.value = '已复制 XML';
  } catch {
    copyState.value = '复制失败，请手动选择文本';
  }
}

async function saveDraft(): Promise<void> {
  await batch.saveDraft();
}

async function requestTransition(target: string): Promise<void> {
  const option = batch.transitions.find((item) => item.target === target);
  pendingTarget.value = target;
  transitionReason.value = '';
  if (option?.requiresReason) {
    reasonDialogOpen.value = true;
    return;
  }
  await batch.changeStatus(target);
}

async function confirmTransition(): Promise<void> {
  const ok = await batch.changeStatus(
    pendingTarget.value,
    transitionReason.value,
    transitionOperator.value,
  );
  if (ok) reasonDialogOpen.value = false;
}

async function submitEarlyEnd(): Promise<void> {
  const ok = await batch.registerEarlyEnd(
    earlyEndReason.value,
    earlyEndOperator.value,
    earlyEndNote.value,
  );
  if (ok) {
    earlyEndOpen.value = false;
    earlyEndReason.value = '';
    earlyEndNote.value = '';
  }
}
</script>

<template>
  <div class="preview">
    <AppCard title="预览与导出" subtitle="XML 由后端阶段 0 的生成器产出，不在前端拼接字符串。">
      <template #actions>
        <AppStatusBadge tone="pending" label="待核对" />
      </template>

      <div class="preview__actions">
        <AppButton variant="primary" :loading="batch.busy" @click="generate">
          <template #icon><FlaskConical :size="16" aria-hidden="true" /></template>
          生成 XML 预览
        </AppButton>
        <AppButton variant="secondary" :disabled="!batch.preview" @click="verifyAgainstGolden">
          <template #icon><CheckCircle2 :size="16" aria-hidden="true" /></template>
          与黄金基准比对
        </AppButton>
        <AppButton variant="secondary" :disabled="!batch.preview" @click="copyXml">
          <template #icon><Copy :size="16" aria-hidden="true" /></template>
          复制 XML
        </AppButton>
        <AppButton variant="ghost" :loading="loadingSample" @click="loadSample('1箱3罐.xml')">
          载入基准样例（1 箱 3 罐）
        </AppButton>
        <AppButton variant="ghost" :loading="loadingSample" @click="loadSample('一箱一罐.xml')">
          载入基准样例（1 箱 1 罐 400 粒）
        </AppButton>
      </div>

      <p v-if="sampleMessage" class="preview__message">{{ sampleMessage }}</p>
      <p v-if="copyState" class="preview__message">{{ copyState }}</p>

      <dl class="preview__stats">
        <div>
          <dt>批号</dt>
          <dd class="code-text">{{ batch.batchNo.trim() || '—' }}</dd>
        </div>
        <div>
          <dt>箱 / 罐 / 粒子</dt>
          <dd class="code-text">
            1 / {{ batch.canCount }} / {{ batch.preview ? batch.plannedParticleTotal : 0 }}
          </dd>
        </div>
        <div>
          <dt>字节长度</dt>
          <dd class="code-text">{{ batch.preview ? batch.preview.length : '—' }}</dd>
        </div>
        <div>
          <dt>SHA-256</dt>
          <dd class="code-text preview__hash">
            {{ batch.previewSha256 ? `${batch.previewSha256.slice(0, 24)}…` : '—' }}
          </dd>
        </div>
      </dl>

      <p v-if="matchesGolden === 'none'" class="preview__banner is-warn" role="status">
        <TriangleAlert :size="16" aria-hidden="true" />
        与两个基准文件都不相同 —— 这是正常的，当前数据与基准样例本就不同。
      </p>
      <p v-else-if="matchesGolden" class="preview__banner is-ok" role="status">
        <CheckCircle2 :size="16" aria-hidden="true" />
        与基准文件 {{ matchesGolden }} 逐字符完全一致。
      </p>
    </AppCard>

    <AppCard
      title="批次生命周期"
      subtitle="状态流转的唯一权威在服务端；这里只发起请求，非法流转会被拒绝。"
    >
      <template #actions>
        <AppStatusBadge
          :tone="(batch.status as never)"
          :label="batch.statusLabel"
          :detail="batch.editable ? undefined : '只读'"
        />
      </template>

      <div class="preview__lifecycle">
        <div class="preview__stage-line">
          <template v-for="(step, index) in ['草稿', '采集中', '待核对', '已核对', '已导出', '已锁定', '已归档']" :key="step">
            <span
              class="preview__stage"
              :class="{ 'is-current': step === batch.statusLabel }"
            >
              {{ step }}
            </span>
            <ArrowRight
              v-if="index < 6"
              :size="14"
              class="preview__stage-arrow"
              aria-hidden="true"
            />
          </template>
        </div>

        <p v-if="!batch.batchId" class="preview__hint">
          尚未保存到本地库。<RouterLink to="/base-info">回到基础信息</RouterLink> 先保存草稿，状态流转才会启用。
        </p>

        <div v-else class="preview__actions">
          <AppButton variant="secondary" :loading="batch.busy" :disabled="!batch.editable" @click="saveDraft">
            <template #icon><Save :size="16" aria-hidden="true" /></template>
            保存修改
          </AppButton>

          <AppButton
            v-for="option in batch.transitions"
            :key="option.target"
            :variant="option.target === 'void' ? 'danger' : 'secondary'"
            :disabled="batch.busy"
            @click="requestTransition(option.target)"
          >
            <template #icon>
              <Undo2 v-if="option.target === 'collecting' || option.target === 'pending_review'" :size="16" aria-hidden="true" />
              <Lock v-else-if="option.target === 'locked'" :size="16" aria-hidden="true" />
              <LogOut v-else-if="option.target === 'void'" :size="16" aria-hidden="true" />
              <ArrowRight v-else :size="16" aria-hidden="true" />
            </template>
            转为「{{ option.label }}」
          </AppButton>
        </div>

        <p v-if="batch.terminal" class="preview__hint">
          当前是终态，不再有可执行的流转。
        </p>
      </div>

      <div class="preview__early-end">
        <div>
          <h4>提前结束</h4>
          <p class="preview__hint">
            实际粒子数少于计划时，默认禁止导出；办理提前结束必须填写原因并选择操作人。
          </p>
        </div>
        <div>
          <AppButton
            v-if="!batch.earlyEnd"
            variant="secondary"
            :disabled="!batch.batchId || !batch.editable"
            @click="earlyEndOpen = true"
          >
            <template #icon><FileWarning :size="16" aria-hidden="true" /></template>
            登记提前结束
          </AppButton>
          <AppButton
            v-else
            variant="ghost"
            :disabled="!batch.editable"
            @click="batch.clearEarlyEnd()"
          >
            撤销提前结束登记
          </AppButton>
        </div>
      </div>

      <dl v-if="batch.earlyEnd" class="preview__stats">
        <div>
          <dt>提前结束原因</dt>
          <dd>{{ batch.earlyEnd.reason }}</dd>
        </div>
        <div>
          <dt>操作人</dt>
          <dd>{{ batch.earlyEnd.operator }}</dd>
        </div>
        <div>
          <dt>备注</dt>
          <dd>{{ batch.earlyEnd.note || '—' }}</dd>
        </div>
        <div>
          <dt>实际罐 / 粒子</dt>
          <dd class="code-text">
            {{ batch.earlyEnd.actualCanCount }} / {{ batch.earlyEnd.actualParticleCount }}
          </dd>
        </div>
        <div>
          <dt>登记时间</dt>
          <dd class="code-text">{{ batch.earlyEnd.at }}</dd>
        </div>
      </dl>
    </AppCard>

    <AppCard v-if="errorIssues.length" title="导出被拦截" subtitle="以下问题必须解决后才能生成 XML。">
      <ul class="preview__issues">
        <li v-for="issue in errorIssues" :key="`${issue.code}-${issue.field}`" class="is-error">
          <FileWarning :size="16" aria-hidden="true" />
          <span>
            <strong>{{ issue.message }}</strong>
            <em class="code-text">{{ issue.code }} · {{ issue.field }}</em>
          </span>
        </li>
      </ul>
    </AppCard>

    <AppCard v-if="warningIssues.length" title="提醒" subtitle="不阻断导出，但请确认。">
      <ul class="preview__issues">
        <li v-for="issue in warningIssues" :key="`${issue.code}-${issue.field}`" class="is-warning">
          <TriangleAlert :size="16" aria-hidden="true" />
          <span>
            <strong>{{ issue.message }}</strong>
            <em class="code-text">{{ issue.code }} · {{ issue.field }}</em>
          </span>
        </li>
      </ul>
    </AppCard>

    <AppCard title="XML 预览" subtitle="原样展示，不做任何格式化改写。">
      <AppEmpty
        v-if="!batch.preview"
        title="尚未生成 XML"
        description="先完成基础信息与包装结构，然后点击「生成 XML 预览」。"
      />
      <div v-else class="preview__code" role="region" aria-label="XML 预览" tabindex="0">
        <div v-for="(line, index) in xmlLines" :key="index" class="preview__line">
          <span class="preview__lineno code-text" aria-hidden="true">{{ index + 1 }}</span>
          <code class="code-text">{{ line }}</code>
        </div>
      </div>

      <template #footer>
        <AppButton variant="ghost" disabled>
          <template #icon><Download :size="16" aria-hidden="true" /></template>
          下载 XML / HTML（阶段 4）
        </AppButton>
      </template>
    </AppCard>

    <AppDialog
      v-model="reasonDialogOpen"
      :title="`转为「${pendingTargetLabel}」`"
      :description="
        pendingNeedsReason
          ? '该操作需要管理员确认并填写原因，结果会写入审计日志。'
          : '确认执行该状态流转。'
      "
      :confirm-label="`确认转为「${pendingTargetLabel}」`"
      :tone="pendingTarget === 'void' ? 'danger' : 'normal'"
      :busy="batch.busy"
      @confirm="confirmTransition"
    >
      <div class="preview__dialog-form">
        <AppInput v-model="transitionReason" label="原因" placeholder="例如：发现条码录入错误，需解锁修正" required />
        <AppInput v-model="transitionOperator" label="操作人" placeholder="填写管理员姓名" required />
      </div>
    </AppDialog>

    <AppDialog
      v-model="earlyEndOpen"
      title="登记提前结束"
      description="提前结束会记录原因、操作人与办理时的实际数量，并写入审计日志。"
      confirm-label="确认提前结束"
      :busy="batch.busy"
      @confirm="submitEarlyEnd"
    >
      <div class="preview__dialog-form">
        <AppInput
          v-model="earlyEndReason"
          label="提前结束原因"
          placeholder="例如：药液不足，本批提前结束"
          required
        />
        <label class="preview__select">
          <span>操作人</span>
          <select v-model="earlyEndOperator">
            <option v-for="name in OPERATORS" :key="name" :value="name">{{ name }}</option>
          </select>
        </label>
        <AppInput v-model="earlyEndNote" label="备注" placeholder="补充说明（可留空）" />
        <p class="preview__hint">
          实际罐数与实际粒子数由服务端按库内数据填写，不受界面影响。
          当前计划 {{ batch.plannedParticleTotal }} 粒、实际 {{ batch.actualParticleTotal }} 粒，
          缺漏 {{ batch.missingParticles }} 粒。
        </p>
      </div>
    </AppDialog>
  </div>
</template>

<style scoped>
.preview {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.preview__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}

.preview__message {
  margin-top: var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.preview__stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--space-4);
  margin: var(--space-5) 0 0;
  padding: var(--space-4);
  background: var(--color-surface-alt);
  border-radius: var(--radius-md);
}

.preview__stats dt {
  font-size: var(--text-xs);
  color: var(--color-text-subtle);
}

.preview__stats dd {
  margin: var(--space-1) 0 0;
  font-size: var(--text-lg);
  font-weight: var(--weight-medium);
}

.preview__hash {
  font-size: var(--text-sm) !important;
}

.preview__banner {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-4);
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  border: 1px solid;
  border-radius: var(--radius-md);
}

.preview__banner.is-ok {
  color: var(--color-success);
  background: var(--color-success-soft);
  border-color: var(--color-success-border);
}

.preview__banner.is-warn {
  color: var(--color-warning);
  background: var(--color-warning-soft);
  border-color: var(--color-warning-border);
}

.preview__issues {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.preview__issues li {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: 1px solid;
  border-radius: var(--radius-md);
}

.preview__issues li span {
  display: flex;
  flex-direction: column;
}

.preview__issues li em {
  font-size: var(--text-xs);
  font-style: normal;
  color: var(--color-text-subtle);
}

.preview__issues li.is-error {
  color: var(--color-danger);
  background: var(--color-danger-soft);
  border-color: var(--color-danger-border);
}

.preview__issues li.is-warning {
  color: var(--color-warning);
  background: var(--color-warning-soft);
  border-color: var(--color-warning-border);
}

/* XML 用等宽 + 行号渲染，不用 textarea；阶段 4 换虚拟化以便承载 12500 粒的长文本 */
.preview__code {
  max-height: 460px;
  overflow: auto;
  background: var(--color-surface-alt);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.preview__lifecycle {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.preview__stage-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.preview__stage {
  padding: 2px var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-subtle);
  background: var(--color-surface-alt);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-pill);
}

/* 当前状态：加粗 + 反色 + 边框，不只靠颜色区分 */
.preview__stage.is-current {
  font-weight: var(--weight-semibold);
  color: var(--color-text-inverse);
  background: var(--color-primary);
  border-color: var(--color-primary-strong);
}

.preview__stage-arrow {
  color: var(--color-text-subtle);
}

.preview__hint {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.preview__early-end {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  margin-top: var(--space-5);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.preview__early-end h4 {
  font-size: var(--text-base);
  font-weight: var(--weight-semibold);
}

.preview__dialog-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.preview__select {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.preview__select span {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text-muted);
}

.preview__select select {
  min-height: var(--touch-target);
  padding: 0 var(--space-3);
  font: inherit;
  color: inherit;
  background: var(--color-surface);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
}

.preview__line {
  display: flex;
  gap: var(--space-3);
  padding: 0 var(--space-4);
  font-size: var(--text-sm);
  line-height: 1.7;
  white-space: pre;
}

.preview__line:hover {
  background: var(--color-primary-soft);
}

.preview__lineno {
  flex-shrink: 0;
  width: 42px;
  color: var(--color-text-subtle);
  text-align: right;
  user-select: none;
}
</style>

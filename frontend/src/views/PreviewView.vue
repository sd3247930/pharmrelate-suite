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
import { computed, onMounted, ref } from 'vue';

import AppDialog from '../components/AppDialog.vue';
import AppButton from '../components/AppButton.vue';
import AppCard from '../components/AppCard.vue';
import AppEmpty from '../components/AppEmpty.vue';
import AppInput from '../components/AppInput.vue';
import AppStatusBadge from '../components/AppStatusBadge.vue';
import AppXmlViewer from '../components/AppXmlViewer.vue';
import { ApiError, api, apiBaseUrl } from '../api/client';
import { useBatchStore } from '../stores/batch';
import { useHotkeys } from '../composables/useHotkeys';
import { addOperator, loadOperators, removeOperator } from '../services/operators';
import type { ExportRecord, Review } from '../types/batch';

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
const review = ref<Review | null>(null);
const reviewError = ref('');

/** 导出闸门以服务端为准：前端只负责如实呈现，不自行判断能不能导。 */
const canExport = computed(() => review.value?.canExport ?? false);
const exportKind = computed(() => review.value?.exportKind ?? 'normal');

async function loadReview(): Promise<void> {
  if (!batch.batchId) {
    review.value = null;
    return;
  }
  reviewError.value = '';
  try {
    review.value = await api.review(batch.batchId);
  } catch (error) {
    review.value = null;
    reviewError.value = error instanceof Error ? error.message : String(error);
  }
}

const exportHistory = ref<ExportRecord[]>([]);
const exportMessage = ref('');

async function loadExports(): Promise<void> {
  if (!batch.batchId) return;
  try {
    exportHistory.value = (await api.exportHistory(batch.batchId)).items;
  } catch {
    exportHistory.value = [];
  }
}

/**
 * 导出并触发浏览器下载。

 * 状态从「已核对」推进到「已导出」由服务端完成，前端不自行改状态；
 * 导出后重新拉核对与记录，保证界面与库一致。
 */
async function downloadExport(kind: 'xml' | 'html'): Promise<void> {
  if (!batch.batchId) return;
  exportMessage.value = '';
  try {
    const result = await api.runExport(batch.batchId, [kind]);
    const item = result.items[0];
    const response = await fetch(`${apiBaseUrl()}${item.downloadUrl}`);
    if (!response.ok) throw new Error(`下载失败（HTTP ${response.status}）`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = item.filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);

    exportMessage.value = `已导出 ${item.filename}（SHA-256 ${item.sha256.slice(0, 16)}…）`;
    await Promise.all([loadExports(), loadReview()]);
    await batch.refreshTransitions();
  } catch (error) {
    exportMessage.value = error instanceof Error ? error.message : String(error);
  }
}

onMounted(() => {
  void loadReview();
  void loadExports();
});

/** F5 刷新核对结果。刷新入口在卡片右上角也有按钮，快捷键只是加速。 */
useHotkeys([{ combo: 'f5', handler: () => void loadReview() }]);

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

/** 操作员名单改为可配置：现场有第五个人时不必改代码。 */
const operators = ref<string[]>(loadOperators());
const manageMessage = ref('');
const newOperator = ref('');
const showOperatorManager = ref(false);

function addOperatorName(): void {
  const value = newOperator.value.trim();
  if (!value) return;
  const before = operators.value.length;
  operators.value = addOperator(operators.value, value);
  manageMessage.value =
    operators.value.length > before ? `已添加 ${value}` : `${value} 已在名单中`;
  newOperator.value = '';
}

function removeOperatorName(name: string): void {
  if (operators.value.length <= 1) {
    manageMessage.value = '至少要保留一个操作员。';
    return;
  }
  operators.value = removeOperator(operators.value, name);
  manageMessage.value = `已移除 ${name}`;
}

const pendingTargetLabel = computed(
  () => batch.transitions.find((item) => item.target === pendingTarget.value)?.label ?? '',
);
const pendingNeedsReason = computed(
  () => batch.transitions.find((item) => item.target === pendingTarget.value)?.requiresReason ?? false,
);

const errorIssues = computed(() => batch.issues.filter((issue) => issue.severity === 'error'));
const warningIssues = computed(() => batch.issues.filter((issue) => issue.severity === 'warning'));

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
    // 提前结束会改变导出闸门，必须重新核对
    await loadReview();
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
      <p v-if="exportMessage" class="preview__message">{{ exportMessage }}</p>

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
      title="整体核对"
      subtitle="计划 vs 实际逐罐对照；缺漏槽位默认禁止导出。"
    >
      <template #actions>
        <AppButton variant="ghost" :disabled="!batch.batchId" @click="loadReview">刷新核对</AppButton>
      </template>

      <p v-if="!batch.batchId" class="preview__hint">
        尚未保存到本地库。<RouterLink to="/base-info">回到基础信息</RouterLink> 先保存草稿。
      </p>
      <p v-else-if="reviewError" class="preview__banner is-warn" role="alert">
        <TriangleAlert :size="16" aria-hidden="true" />
        {{ reviewError }}
      </p>

      <template v-else-if="review">
        <div class="preview__compare">
          <table>
            <thead>
              <tr>
                <th>项目</th>
                <th>计划</th>
                <th>实际</th>
                <th>差异</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>罐</td>
                <td class="code-text">{{ review.plan.canCount }}</td>
                <td class="code-text">{{ review.actual.canCount }}</td>
                <td
                  class="code-text"
                  :class="{ 'is-bad': review.plan.canCount !== review.actual.canCount }"
                >
                  {{ review.actual.canCount - review.plan.canCount }}
                </td>
              </tr>
              <tr>
                <td>粒子</td>
                <td class="code-text">{{ review.plan.particleTotal.toLocaleString('en-US') }}</td>
                <td class="code-text">{{ review.actual.particleTotal.toLocaleString('en-US') }}</td>
                <td class="code-text" :class="{ 'is-bad': review.missingParticles > 0 }">
                  {{ review.actual.particleTotal - review.plan.particleTotal }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <table class="preview__per-can">
          <thead>
            <tr>
              <th>罐</th>
              <th>罐号</th>
              <th>计划</th>
              <th>实际</th>
              <th>缺漏</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in review.perCan" :key="row.index" :class="{ 'is-missing': row.missing > 0 }">
              <td>{{ row.index }}</td>
              <td class="code-text">{{ row.canCode || '—' }}</td>
              <td class="code-text">{{ row.planned }}</td>
              <td class="code-text">{{ row.scanned }}</td>
              <!-- 缺漏用红色 + 数字 + 文字三重表达，不只靠颜色 -->
              <td class="code-text preview__missing">
                <template v-if="row.missing > 0">
                  <TriangleAlert :size="14" aria-hidden="true" />
                  缺 {{ row.missing }}
                </template>
                <template v-else>0</template>
              </td>
              <td>
                <span v-if="row.complete" class="preview__tag is-ok">已完成</span>
                <span v-else-if="row.scanned === 0" class="preview__tag is-empty">未开始</span>
                <span v-else class="preview__tag is-partial">进行中</span>
              </td>
            </tr>
          </tbody>
        </table>

        <ul class="preview__checks">
          <li v-for="item in review.checks" :key="item.code" :class="item.passed ? 'is-ok' : 'is-bad'">
            <component :is="item.passed ? CheckCircle2 : TriangleAlert" :size="16" aria-hidden="true" />
            <span>
              <strong>{{ item.label }}</strong>
              <em>{{ item.detail }}</em>
            </span>
          </li>
        </ul>

        <ul v-if="review.blocking.length" class="preview__issues">
          <li v-for="item in review.blocking" :key="item.code" class="is-error">
            <FileWarning :size="16" aria-hidden="true" />
            <span>
              <strong>{{ item.message }}</strong>
              <em>{{ item.action }}</em>
            </span>
          </li>
        </ul>

        <div class="preview__export">
          <AppButton
            variant="primary"
            :disabled="!canExport"
            :title="canExport ? '生成 XML / HTML' : '存在未解决的问题，导出已被禁止'"
          >
            <template #icon><Download :size="16" aria-hidden="true" /></template>
            {{ exportKind === 'early_end' ? '生成 XML / HTML（提前结束）' : '生成 XML / HTML' }}
          </AppButton>
          <p v-if="!canExport" class="preview__hint">
            导出已被禁止，请先处理上方问题。
          </p>
          <p v-else-if="exportKind === 'early_end'" class="preview__hint">
            本批为提前结束，导出内容仅包含实际录入数据，并会在审计日志中标记。
          </p>
          <p v-else class="preview__hint">
            核对通过，可以导出。文件名与 SHA-256 会在导出记录中留下。
          </p>
        </div>
      </template>
    </AppCard>

    <AppCard title="导出记录" subtitle="每次导出都留一条不可变记录，哈希与文件内容一一对应。">
      <AppEmpty
        v-if="!exportHistory.length"
        title="还没有导出记录"
        description="完成核对后点击「导出 XML」或「导出 HTML」，这里会显示文件名、SHA-256 与导出时间。"
      />
      <table v-else class="preview__exports">
        <thead>
          <tr>
            <th>文件名</th>
            <th>格式</th>
            <th>粒子数</th>
            <th>字节</th>
            <th>SHA-256</th>
            <th>导出类型</th>
            <th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in exportHistory" :key="item.id">
            <td class="code-text">{{ item.filename }}</td>
            <td>{{ item.kind.toUpperCase() }}</td>
            <td class="code-text">{{ item.particleTotal }}</td>
            <td class="code-text">{{ item.byteLength.toLocaleString('en-US') }}</td>
            <td class="code-text preview__hash">{{ item.sha256.slice(0, 16) }}…</td>
            <td>
              <span class="preview__tag" :class="item.exportKind === 'early_end' ? 'is-partial' : 'is-ok'">
                {{ item.exportKind === 'early_end' ? '提前结束' : '正常' }}
              </span>
            </td>
            <td class="code-text preview__updated">{{ item.createdAt }}</td>
          </tr>
        </tbody>
      </table>
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
        <AppXmlViewer :value="batch.preview" :height="420" />
      </div>

      <template #footer>
        <!-- 导出不依赖"先生成预览"：预览只是给人看的，导出用的是服务端的数据。 -->
        <AppButton variant="secondary" :disabled="!batch.batchId" @click="downloadExport('xml')">
          <template #icon><Download :size="16" aria-hidden="true" /></template>
          导出 XML
        </AppButton>
        <AppButton variant="secondary" :disabled="!batch.batchId" @click="downloadExport('html')">
          <template #icon><Download :size="16" aria-hidden="true" /></template>
          导出 HTML
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
            <option v-for="name in operators" :key="name" :value="name">{{ name }}</option>
          </select>
        </label>
        <div>
          <AppButton variant="ghost" @click="showOperatorManager = !showOperatorManager">
            {{ showOperatorManager ? '收起名单管理' : '管理操作员名单' }}
          </AppButton>
        </div>
        <div v-if="showOperatorManager" class="preview__operators">
          <ul>
            <li v-for="name in operators" :key="name">
              <span>{{ name }}</span>
              <AppButton variant="ghost" @click="removeOperatorName(name)">移除</AppButton>
            </li>
          </ul>
          <div class="preview__operator-add">
            <AppInput v-model="newOperator" label="新增操作员" placeholder="姓名" />
            <AppButton variant="secondary" @click="addOperatorName">添加</AppButton>
          </div>
          <p v-if="manageMessage" class="preview__hint">{{ manageMessage }}</p>
        </div>
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

.preview__compare table,
.preview__per-can {
  margin-top: var(--space-3);
  font-size: var(--text-sm);
}

.preview__per-can td,
.preview__per-can th {
  padding: var(--space-2) var(--space-3);
}

/* 缺漏行用左侧色条 + 红字，颜色不是唯一线索 */
.preview__per-can tr.is-missing {
  background: var(--color-danger-soft);
  box-shadow: inset 3px 0 0 var(--color-danger);
}

.preview__missing {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--color-danger);
  font-weight: var(--weight-semibold);
}

.preview__tag {
  padding: 1px var(--space-2);
  font-size: var(--text-xs);
  border: 1px solid;
  border-radius: var(--radius-pill);
  white-space: nowrap;
}

.preview__tag.is-ok {
  color: var(--color-success);
  background: var(--color-success-soft);
  border-color: var(--color-success-border);
}

.preview__tag.is-partial {
  color: var(--color-warning);
  background: var(--color-warning-soft);
  border-color: var(--color-warning-border);
}

.preview__tag.is-empty {
  color: var(--color-text-subtle);
  background: var(--color-surface-sunken);
  border-color: var(--color-border);
}

.preview__checks {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: var(--space-4) 0 0;
  padding: 0;
  list-style: none;
}

.preview__checks li {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  font-size: var(--text-sm);
}

.preview__checks li span {
  display: flex;
  flex-direction: column;
}

.preview__checks li em {
  font-style: normal;
  color: var(--color-text-muted);
}

.preview__checks li.is-ok {
  color: var(--color-success);
}

.preview__checks li.is-bad {
  color: var(--color-danger);
}

.preview__export {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-top: var(--space-5);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.is-bad {
  color: var(--color-danger);
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

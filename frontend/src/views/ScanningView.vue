<script setup lang="ts">
import {
  Camera,
  CameraOff,
  CheckCircle2,
  ChevronRight,
  Cylinder,
  Keyboard,
  RotateCcw,
  ScanLine,
  TriangleAlert,
  Trash2,
  Undo2,
  Redo2,
  RefreshCw,
  Volume2,
  VolumeX,
} from 'lucide-vue-next';
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';

import AppButton from '../components/AppButton.vue';
import AppCard from '../components/AppCard.vue';
import AppInput from '../components/AppInput.vue';
import AppProgress from '../components/AppProgress.vue';
import AppStatusBadge from '../components/AppStatusBadge.vue';
import AppSlotGrid from '../components/AppSlotGrid.vue';
import { cameraFrameUrl } from '../api/client';
import {
  getAlarmSettings,
  isUnlocked,
  playAlarm,
  unlockAudio,
  updateAlarmSettings,
} from '../services/alarm';
import { useBatchStore } from '../stores/batch';
import { useScanStore } from '../stores/scan';
import { classifyCode, CODE_LENGTH, LAYER_LABELS } from '../types/batch';
import type { CanPayload } from '../types/batch';
import { buildSlots, slotsOfCan, summarizeSlots, type Slot } from '../services/slotGrid';

/**
 * 界面 3：扫码采集。

 * 三条输入路径（拍照识别 / 条码枪 HID / 手动输入）最终都汇到同一个会话 API，
 * 因此拦截规则、去重、审计只实现一次。
 *
 * 状态一律由后端返回，前端只提交"识别到了什么"和"操作员点了什么"。
 */
const router = useRouter();
const batch = useBatchStore();
const scan = useScanStore();

const manualCode = ref('');
const manualError = ref('');
const frameTick = ref(0);
const alarmSettings = ref(getAlarmSettings());
const audioReady = ref(isUnlocked());
const probe = ref('');
const selectedSlot = ref<Slot | null>(null);
const replaceCode = ref('');
const replaceError = ref('');
const slotGrid = ref<InstanceType<typeof AppSlotGrid> | null>(null);
let frameTimer: number | undefined;

const batchId = computed(() => batch.batchId);
const canContinue = computed(() => batchId.value !== '');

/** 条码层级校验器保留为独立小工具：现场遇到可疑条码时可直接判断层级。 */
const probeResult = computed(() => {
  const value = probe.value.trim();
  if (!value) return null;
  if (value.length !== CODE_LENGTH || !/^\d+$/.test(value)) {
    return { ok: false, title: '不是合法条码', detail: `必须是 ${CODE_LENGTH} 位 ASCII 数字。` };
  }
  const layer = classifyCode(value);
  if (layer === null) {
    return { ok: false, title: '前缀不在白名单内', detail: '箱 8021761 / 罐 8021762 / 粒子 8206233。' };
  }
  return { ok: true, title: `这是${LAYER_LABELS[layer]}`, detail: `packLayer=${layer}` };
});

const stageHint = computed(() => {
  switch (scan.scanMode) {
    case 'single':
      return `要求：当前画面只能出现 1 个条码（${scan.statusLabel}）`;
    case 'batch':
      return `本罐剩余 ${scan.remainingInCan} 个槽位，可一次识别多个粒子码`;
    default:
      return '当前状态不需要扫描，请按下方提示操作';
  }
});

/**
 * 槽位视图由「计划 + 实际」两个来源合成：槽位数来自计划，条码来自实际。
 * 因此缺漏槽位天然可见（空槽），扫描超出计划也会被标成冲突而不是悄悄丢掉。
 */
const currentSlots = computed(() => {
  const plan = scan.snapshot?.canPlan ?? [];
  const cans: CanPayload[] = (scan.snapshot?.canPlan ?? []).map((planned, offset) => ({
    index: offset + 1,
    code: scan.snapshot?.canCodes[offset] ?? '',
    plannedParticleCount: planned,
    particles: scan.snapshot?.canParticles[offset] ?? [],
  }));
  return slotsOfCan(buildSlots(plan, cans), scan.currentCan);
});

const slotSummary = computed(() => summarizeSlots(currentSlots.value));

function selectSlot(slot: Slot): void {
  selectedSlot.value = selectedSlot.value?.index === slot.index ? null : slot;
  replaceCode.value = '';
  replaceError.value = '';
}

/**
 * 重复扫码被拒绝时，直接把操作员带到那个槽位。

 * 只说"条码已被使用"帮助有限 —— 真正要回答的是"它绑在哪儿"，
 * 而槽位可能有几千个，靠人翻是找不到的。
 */
watch(
  () => scan.blocked?.detail?.code,
  (code) => {
    if (typeof code !== 'string' || !code) return;
    const index = currentSlots.value.findIndex((slot) => slot.code === code);
    if (index >= 0) {
      selectedSlot.value = currentSlots.value[index];
      slotGrid.value?.scrollToIndex(index);
    }
  },
);

async function deleteSelectedSlot(): Promise<void> {
  const slot = selectedSlot.value;
  if (!slot?.code) return;
  const ok = await scan.removeSlot(batchId.value, slot.code);
  if (ok) selectedSlot.value = null;
}

async function replaceSelectedSlot(): Promise<void> {
  const slot = selectedSlot.value;
  const value = replaceCode.value.trim();
  if (!slot?.code || !value) return;
  replaceError.value = '';
  if (classifyCode(value) !== 1) {
    replaceError.value = '粒子槽位只接受粒子码（8206233 开头）。';
    return;
  }
  const ok = await scan.replaceSlot(batchId.value, slot.code, value);
  if (ok) {
    selectedSlot.value = null;
    replaceCode.value = '';
  }
}

function enableAudio(): void {
  audioReady.value = unlockAudio();
  if (audioReady.value) playAlarm('scan-success');
}

function toggleSound(): void {
  alarmSettings.value = updateAlarmSettings({ enabled: !alarmSettings.value.enabled });
}

async function submitManual(): Promise<void> {
  manualError.value = '';
  const raw = manualCode.value.trim();
  if (!raw) return;
  if (!audioReady.value) audioReady.value = unlockAudio();

  // 条码枪以 HID 键盘方式输入时可能一次带入多行，按行切分成多个码
  const codes = raw.split(/[\s,;]+/).filter(Boolean);
  const ok = await scan.submitCodes(batchId.value, codes);
  if (ok) manualCode.value = '';
}

function onManualKeydown(event: KeyboardEvent): void {
  // 条码枪通常以 Enter 结尾，直接提交，不需要操作员去点按钮
  if (event.key === 'Enter') {
    event.preventDefault();
    void submitManual();
  }
}

async function startCamera(): Promise<void> {
  if (!audioReady.value) audioReady.value = unlockAudio();
  const started = await scan.startCamera(batchId.value, 'opencv');
  if (started) refreshFrameLoop();
}

async function startTestSource(): Promise<void> {
  if (!audioReady.value) audioReady.value = unlockAudio();
  const started = await scan.startCamera(batchId.value, 'test_image');
  if (started) refreshFrameLoop();
}

async function stopCamera(): Promise<void> {
  await scan.stopCamera();
  if (frameTimer !== undefined) {
    window.clearInterval(frameTimer);
    frameTimer = undefined;
  }
}

function refreshFrameLoop(): void {
  if (frameTimer !== undefined) window.clearInterval(frameTimer);
  // 画面每 400ms 拉一次，与后端 300ms 的识别节流错开但保持接近实时
  frameTimer = window.setInterval(() => {
    frameTick.value += 1;
  }, 400);
}

async function syncSession(): Promise<void> {
  if (!canContinue.value) return;
  await scan.load(batchId.value);
  if (scan.cameraRunning) refreshFrameLoop();
}

onMounted(() => {
  void syncSession();
});

onBeforeUnmount(() => {
  if (frameTimer !== undefined) window.clearInterval(frameTimer);
  void scan.stopCamera();
});
</script>

<template>
  <div class="scan">
    <AppCard title="扫码采集" subtitle="状态由服务端权威控制，界面只提交识别结果与操作员动作。">
      <template #actions>
        <AppStatusBadge tone="collecting" :label="scan.statusLabel" />
        <AppButton variant="ghost" @click="toggleSound">
          <template #icon>
            <Volume2 v-if="alarmSettings.enabled" :size="16" aria-hidden="true" />
            <VolumeX v-else :size="16" aria-hidden="true" />
          </template>
          {{ alarmSettings.enabled ? '声音开' : '声音关' }}
        </AppButton>
      </template>

      <p v-if="!canContinue" class="scan__notice" role="status">
        <TriangleAlert :size="16" aria-hidden="true" />
        尚未选择批次。<RouterLink to="/base-info">回到基础信息</RouterLink> 创建并保存草稿后即可扫码。
      </p>

      <p v-else-if="!audioReady" class="scan__notice scan__notice--warn" role="status">
        <VolumeX :size="16" aria-hidden="true" />
        浏览器要求先有一次交互才能播放报警音。
        <AppButton variant="secondary" @click="enableAudio">点击启用声音</AppButton>
      </p>

      <!-- 拦截 / 报警：颜色 + 图标 + 文字三重表达，并给出恢复路径 -->
      <p
        v-if="scan.blocked"
        class="scan__alarm"
        :class="scan.blocked.needsAlarm ? 'is-error' : 'is-warning'"
        role="alert"
      >
        <TriangleAlert :size="20" aria-hidden="true" />
        <span>
          <strong>{{ scan.blocked.label }}：{{ scan.blocked.message }}</strong>
          <em v-if="scan.blocked.detail?.usedAt">
            已绑定位置：{{ scan.blocked.detail.usedAt }}
          </em>
          <em v-else-if="scan.blocked.detail?.remaining !== undefined">
            本罐剩余 {{ scan.blocked.detail.remaining }} 个槽位，本次识别
            {{ scan.blocked.detail.incoming }} 个
          </em>
        </span>
      </p>

      <p v-if="scan.errorMessage && !scan.blocked" class="scan__alarm is-error" role="alert">
        <TriangleAlert :size="20" aria-hidden="true" />
        <span><strong>{{ scan.errorMessage }}</strong></span>
      </p>

      <div class="scan__grid">
        <!-- 左：任务与进度 -->
        <section class="scan__panel">
          <h3>当前任务</h3>
          <dl class="scan__facts">
            <div>
              <dt>批号</dt>
              <dd class="code-text">{{ batch.batchNo || '—' }}</dd>
            </div>
            <div>
              <dt>罐</dt>
              <dd class="code-text">{{ scan.currentCan }} / {{ scan.plannedCanCount }}</dd>
            </div>
            <div>
              <dt>本罐粒子</dt>
              <dd class="code-text">{{ scan.currentCanScanned }} / {{ scan.currentCanPlanned }}</dd>
            </div>
            <div>
              <dt>总计</dt>
              <dd class="code-text">
                {{ scan.snapshot?.actualParticleTotal ?? 0 }} / {{ scan.snapshot?.plannedParticleTotal ?? 0 }}
              </dd>
            </div>
          </dl>

          <AppProgress
            :value="scan.currentCanScanned"
            :max="Math.max(1, scan.currentCanPlanned)"
            label="本罐进度"
          />

          <p v-if="scan.missingParticles" class="scan__hint">
            尚有 <strong class="code-text">{{ scan.missingParticles }}</strong> 个槽位未完成
          </p>

          <div class="scan__history">
            <AppButton
              variant="secondary"
              :disabled="!scan.history.canUndo || scan.busy"
              :title="scan.history.undoLabel || '没有可撤销的操作'"
              @click="scan.undo(batchId)"
            >
              <template #icon><Undo2 :size="16" aria-hidden="true" /></template>
              撤销
            </AppButton>
            <AppButton
              variant="secondary"
              :disabled="!scan.history.canRedo || scan.busy"
              :title="scan.history.redoLabel || '没有可重做的操作'"
              @click="scan.redo(batchId)"
            >
              <template #icon><Redo2 :size="16" aria-hidden="true" /></template>
              重做
            </AppButton>
          </div>
          <p class="scan__hint">
            可撤销 {{ scan.history.canUndo }} 步 / 可重做 {{ scan.history.canRedo }} 步（上限
            {{ scan.history.maxSteps }}）
          </p>
        </section>

        <!-- 中：取景与输入 -->
        <section class="scan__panel scan__panel--view">
          <h3>取景 / 输入</h3>

          <div class="scan__viewport">
            <img
              v-if="scan.cameraRunning"
              :src="cameraFrameUrl(frameTick)"
              alt="摄像头实时画面"
            />
            <div v-else class="scan__viewport-empty">
              <component :is="scan.cameraError ? CameraOff : Camera" :size="36" aria-hidden="true" />
              <p>{{ scan.cameraError ? '摄像头未就绪' : '摄像头未开启' }}</p>
              <p v-if="scan.cameraHint" class="scan__hint">{{ scan.cameraHint }}</p>
            </div>
          </div>

          <p class="scan__hint">{{ stageHint }}</p>

          <div class="scan__actions">
            <AppButton v-if="!scan.cameraRunning" variant="secondary" @click="startCamera">
              <template #icon><Camera :size="16" aria-hidden="true" /></template>
              开启摄像头
            </AppButton>
            <AppButton v-else variant="secondary" @click="stopCamera">
              <template #icon><CameraOff :size="16" aria-hidden="true" /></template>
              关闭摄像头
            </AppButton>
            <AppButton variant="ghost" @click="startTestSource">用测试图源</AppButton>
          </div>

          <div class="scan__manual">
            <AppInput
              v-model="manualCode"
              label="手动输入 / 条码枪"
              placeholder="粘贴或扫描条码，多个码用空格或换行分隔"
              monospace
              :error="manualError"
              hint="条码枪以回车结尾，可直接提交，无需点按钮。"
              @keydown="onManualKeydown"
            />
            <AppButton variant="primary" :loading="scan.busy" @click="submitManual">
              <template #icon><Keyboard :size="16" aria-hidden="true" /></template>
              提交
            </AppButton>
          </div>
        </section>

        <!-- 右：罐进度一览与动作 -->
        <section class="scan__panel">
          <h3>罐 {{ scan.currentCan }} 的槽位</h3>
          <p class="scan__hint">
            已扫 {{ slotSummary.scanned }} / {{ slotSummary.total }}
            <template v-if="slotSummary.missing">· 缺漏 {{ slotSummary.missing }}</template>
            <template v-if="slotSummary.conflict">· 异常 {{ slotSummary.conflict }}</template>
          </p>

          <AppSlotGrid
            ref="slotGrid"
            :slots="currentSlots"
            :selected-index="selectedSlot?.index ?? null"
            :height="220"
            @select="selectSlot"
          />

          <div v-if="selectedSlot" class="scan__slot-detail">
            <p class="scan__slot-title">
              粒子槽位 {{ selectedSlot.index }}
              <span v-if="selectedSlot.code" class="code-text">{{ selectedSlot.code }}</span>
              <span v-else>（空槽）</span>
            </p>
            <template v-if="selectedSlot.code">
              <AppInput
                v-model="replaceCode"
                label="替换为新条码"
                placeholder="扫描或输入新的粒子码"
                monospace
                :error="replaceError"
              />
              <div class="scan__actions">
                <AppButton variant="secondary" :loading="scan.busy" @click="replaceSelectedSlot">
                  <template #icon><RefreshCw :size="16" aria-hidden="true" /></template>
                  替换
                </AppButton>
                <AppButton variant="danger" :loading="scan.busy" @click="deleteSelectedSlot">
                  <template #icon><Trash2 :size="16" aria-hidden="true" /></template>
                  删除
                </AppButton>
              </div>
            </template>
            <p v-else class="scan__hint">空槽无需操作，继续扫描即可填入。</p>
          </div>

          <h3>各罐进度</h3>
          <ul class="scan__cans">
            <li
              v-for="(planned, index) in scan.snapshot?.canPlan ?? []"
              :key="index"
              :class="{ 'is-current': index + 1 === scan.currentCan }"
            >
              <Cylinder :size="15" aria-hidden="true" />
              <span>罐 {{ index + 1 }}</span>
              <span class="code-text">{{ scan.snapshot?.canScanned[index] ?? 0 }} / {{ planned }}</span>
              <CheckCircle2
                v-if="(scan.snapshot?.canScanned[index] ?? 0) >= planned"
                :size="15"
                class="scan__ok"
                aria-hidden="true"
              />
            </li>
          </ul>

          <div class="scan__actions scan__actions--stack">
            <AppButton
              v-if="scan.status === 'box_confirm' || scan.status === 'can_confirm'"
              variant="primary"
              :loading="scan.busy"
              @click="scan.confirm(batchId)"
            >
              <template #icon><CheckCircle2 :size="16" aria-hidden="true" /></template>
              确认 {{ scan.snapshot?.pendingCode }}
            </AppButton>

            <AppButton
              v-if="scan.status === 'box_confirm' || scan.status === 'can_confirm' || scan.status === 'can_review'"
              variant="secondary"
              :loading="scan.busy"
              @click="scan.rescan(batchId)"
            >
              <template #icon><RotateCcw :size="16" aria-hidden="true" /></template>
              {{ scan.status === 'can_review' ? '还没好，继续拍' : '重拍' }}
            </AppButton>

            <AppButton
              v-if="scan.status === 'can_review'"
              variant="primary"
              :loading="scan.busy"
              @click="scan.confirm(batchId)"
            >
              <template #icon><CheckCircle2 :size="16" aria-hidden="true" /></template>
              本罐确认无误
            </AppButton>

            <template v-if="scan.status === 'next_can_prompt'">
              <AppButton variant="primary" :loading="scan.busy" @click="scan.nextCan(batchId, true)">
                <template #icon><ChevronRight :size="16" aria-hidden="true" /></template>
                继续下一罐
              </AppButton>
              <AppButton variant="secondary" :loading="scan.busy" @click="scan.nextCan(batchId, false)">
                提前结束
              </AppButton>
            </template>

            <AppButton
              v-if="scan.status === 'overall_review' || scan.status === 'early_end'"
              variant="primary"
              @click="router.push('/preview')"
            >
              <template #icon><ScanLine :size="16" aria-hidden="true" /></template>
              前往整体核对
            </AppButton>
          </div>

          <p class="scan__hint">
            冲突 {{ scan.snapshot?.conflictCount ?? 0 }} 次 · 报警
            {{ scan.snapshot?.alarmCount ?? 0 }} 次
          </p>
        </section>
      </div>
    </AppCard>

    <AppCard title="条码层级校验器" subtitle="真实可用：粘入条码即可判断它属于箱、罐还是粒子。">
      <AppInput v-model="probe" label="条码" placeholder="粘贴 20 位条码" monospace />
      <p v-if="probeResult" class="scan__probe" :class="probeResult.ok ? 'is-ok' : 'is-bad'" role="status">
        <component :is="probeResult.ok ? CheckCircle2 : TriangleAlert" :size="18" aria-hidden="true" />
        <span>
          <strong>{{ probeResult.title }}</strong>
          <em>{{ probeResult.detail }}</em>
        </span>
      </p>
    </AppCard>
  </div>
</template>

<style scoped>
.scan {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.scan__grid {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) minmax(320px, 1.6fr) minmax(220px, 1fr);
  gap: var(--space-5);
  margin-top: var(--space-4);
}

@media (max-width: 1280px) {
  .scan__grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

.scan__panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-4);
  background: var(--color-surface-alt);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.scan__panel h3 {
  font-size: var(--text-base);
}

.scan__facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
  margin: 0;
}

.scan__facts dt {
  font-size: var(--text-xs);
  color: var(--color-text-subtle);
}

.scan__facts dd {
  margin: 2px 0 0;
  font-size: var(--text-lg);
  font-weight: var(--weight-medium);
}

.scan__viewport {
  display: grid;
  place-items: center;
  aspect-ratio: 4 / 3;
  overflow: hidden;
  background: var(--color-surface-sunken);
  border: 2px dashed var(--color-border-strong);
  border-radius: var(--radius-md);
}

.scan__viewport img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.scan__viewport-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-muted);
  text-align: center;
}

.scan__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.scan__actions--stack {
  flex-direction: column;
}

.scan__manual {
  display: flex;
  align-items: flex-end;
  gap: var(--space-2);
}

.scan__manual :deep(.app-input) {
  flex: 1;
}

.scan__cans {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.scan__cans li {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
}

.scan__cans li.is-current {
  font-weight: var(--weight-semibold);
  border-color: var(--color-primary);
  box-shadow: inset 3px 0 0 var(--color-primary);
}

.scan__cans li span:nth-child(3) {
  margin-left: auto;
}

.scan__ok {
  color: var(--color-success);
}

.scan__alarm {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  margin-top: var(--space-4);
  padding: var(--space-3) var(--space-4);
  border: 1px solid;
  border-radius: var(--radius-md);
}

.scan__alarm span {
  display: flex;
  flex-direction: column;
}

.scan__alarm em {
  font-size: var(--text-sm);
  font-style: normal;
  color: var(--color-text-muted);
}

.scan__alarm.is-error {
  color: var(--color-danger);
  background: var(--color-danger-soft);
  border-color: var(--color-danger-border);
}

.scan__alarm.is-warning {
  color: var(--color-warning);
  background: var(--color-warning-soft);
  border-color: var(--color-warning-border);
}

.scan__notice {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  background: var(--color-surface-sunken);
  border-radius: var(--radius-md);
}

.scan__notice--warn {
  color: var(--color-warning);
  background: var(--color-warning-soft);
}

.scan__hint {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.scan__history {
  display: flex;
  gap: var(--space-2);
}

.scan__slot-detail {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3);
  background: var(--color-surface);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
}

.scan__slot-title {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
}

.scan__probe {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  margin-top: var(--space-4);
  padding: var(--space-3) var(--space-4);
  border: 1px solid;
  border-radius: var(--radius-md);
}

.scan__probe span {
  display: flex;
  flex-direction: column;
}

.scan__probe em {
  font-size: var(--text-sm);
  font-style: normal;
  color: var(--color-text-muted);
}

.scan__probe.is-ok {
  color: var(--color-success);
  background: var(--color-success-soft);
  border-color: var(--color-success-border);
}

.scan__probe.is-bad {
  color: var(--color-danger);
  background: var(--color-danger-soft);
  border-color: var(--color-danger-border);
}
</style>

<script setup lang="ts">
import { FileCheck2, FileUp, FolderOpen, ScanLine, ShieldAlert, ShieldCheck, TrendingUp } from 'lucide-vue-next';
import { computed, onMounted, ref } from 'vue';
import { RouterLink, useRouter } from 'vue-router';

import AppBatchNoConflictDialog from '../components/AppBatchNoConflictDialog.vue';
import AppButton from '../components/AppButton.vue';
import AppCard from '../components/AppCard.vue';
import AppEmpty from '../components/AppEmpty.vue';
import AppProgress from '../components/AppProgress.vue';
import AppStatusBadge from '../components/AppStatusBadge.vue';
import { useBatchStore } from '../stores/batch';
import { useSystemStore } from '../stores/system';
import { MAX_PARTICLES_PER_BATCH } from '../types/batch';

/**
 * 工作台不是统计大屏，而是"车间当前状态总览"。
 *
 * 刻意不堆彩色 KPI 卡片：只保留当前批次、基准一致性、下一步动作三块。
 */
const batch = useBatchStore();
const system = useSystemStore();
const router = useRouter();

const hasDraft = computed(() => batch.batchNo.trim().length > 0);
const fileInput = ref<HTMLInputElement | null>(null);

const conflictOpen = computed({
  get: () => batch.conflict !== null,
  set: (value: boolean) => {
    if (!value) batch.dismissConflict();
  },
});

onMounted(() => {
  void batch.refreshBatchList();
});

const nextStep = computed(() => {
  if (!hasDraft.value) return { to: '/base-info', label: '开始创建批次' };
  if (batch.plannedParticleTotal < 1) return { to: '/package-structure', label: '设置包装结构' };
  return { to: '/preview', label: '生成 XML 预览' };
});

/**
 * 导入 XML：文件读成文本交给服务端解析，成功则回填并进入预览页。

 * 前端不做任何 XML 解析 —— 解析与校验只有服务端一份，
 * 否则"什么是合法 XML"就有了两个答案。
 */
async function importFile(file: File): Promise<void> {
  const text = await file.text();
  const ok = await batch.importXml(text, file.name);
  if (ok) router.push('/preview');
}

async function onPickFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  // 清空，保证同一个文件可以连续导入两次（例如改完再导一次）
  input.value = '';
  if (file) await importFile(file);
}

async function onDropFile(event: DragEvent): Promise<void> {
  const file = event.dataTransfer?.files?.[0];
  if (file) await importFile(file);
}

async function openConflictExisting(): Promise<void> {
  const id = batch.conflict?.existing.id;
  batch.dismissConflict();
  if (id && (await batch.openExisting(id))) router.push('/preview');
}

async function createNewVersionFromImport(): Promise<void> {
  if (await batch.importXmlAsNewVersion()) router.push('/preview');
}
</script>

<template>
  <div class="dashboard">
    <div class="dashboard__grid">
      <AppCard title="当前批次" subtitle="草稿保存在本次会话中，阶段 2 接入本地数据库持久化。">
        <template #actions>
          <AppStatusBadge tone="draft" />
        </template>

        <dl class="dashboard__facts">
          <div>
            <dt>批号</dt>
            <dd class="code-text">{{ batch.batchNo.trim() || '未填写' }}</dd>
          </div>
          <div>
            <dt>生产日期</dt>
            <dd class="code-text">{{ batch.madeDate }}</dd>
          </div>
          <div>
            <dt>有效期</dt>
            <dd class="code-text">{{ batch.validateDate }}</dd>
          </div>
          <div>
            <dt>箱号</dt>
            <dd class="code-text">{{ batch.boxCode.trim() || '未填写' }}</dd>
          </div>
          <div>
            <dt>罐 / 计划粒子</dt>
            <dd class="code-text">{{ batch.canCount }} 罐 / {{ batch.plannedParticleTotal }} 粒</dd>
          </div>
        </dl>

        <div class="dashboard__progress">
          <AppProgress
            :value="batch.plannedParticleTotal"
            :max="MAX_PARTICLES_PER_BATCH"
            label="占单批次上限"
            :tone="batch.overBatchLimit ? 'danger' : 'normal'"
          />
          <p class="dashboard__limit code-text">
            {{ batch.plannedParticleTotal }} / {{ MAX_PARTICLES_PER_BATCH }}
          </p>
        </div>

        <template #footer>
          <RouterLink to="/base-info"><AppButton variant="secondary">编辑基础信息</AppButton></RouterLink>
          <RouterLink :to="nextStep.to">
            <AppButton variant="primary">
              <template #icon><ScanLine :size="16" aria-hidden="true" /></template>
              {{ nextStep.label }}
            </AppButton>
          </RouterLink>
        </template>
      </AppCard>

      <AppCard title="环境自检" subtitle="每次进入工作台都会重新验证，避免带病作业。">
        <ul class="dashboard__checks">
          <li>
            <component
              :is="system.isOnline ? ShieldCheck : ShieldAlert"
              :size="18"
              :class="system.isOnline ? 'ok' : 'bad'"
              aria-hidden="true"
            />
            <div>
              <p class="dashboard__check-title">本地服务</p>
              <p class="dashboard__check-detail">
                {{ system.isOnline ? `已连接 · v${system.version} · Python ${system.pythonVersion}` : '未连接' }}
              </p>
            </div>
          </li>
          <li>
            <component
              :is="system.goldenOk ? ShieldCheck : ShieldAlert"
              :size="18"
              :class="system.goldenOk ? 'ok' : 'bad'"
              aria-hidden="true"
            />
            <div>
              <p class="dashboard__check-title">黄金基准</p>
              <p class="dashboard__check-detail">
                {{ system.goldenOk ? '两个基准文件均字节级一致' : '基准文件往返校验未通过' }}
              </p>
            </div>
          </li>
        </ul>

        <ul v-if="system.golden.length" class="dashboard__golden">
          <li v-for="item in system.golden" :key="item.name">
            <FileCheck2 :size="15" :class="item.roundtripOk ? 'ok' : 'bad'" aria-hidden="true" />
            <span>{{ item.name }}</span>
            <span class="code-text">{{ item.byteLength.toLocaleString('en-US') }} 字节</span>
            <span class="code-text dashboard__hash">{{ item.sha256.slice(0, 12) }}…</span>
          </li>
        </ul>
      </AppCard>
    </div>

    <AppCard
      title="导入 XML"
      subtitle="把一期格式的关联关系 XML 读回软件，新建批次并把各页面填好。"
    >
      <div class="dashboard__import" @dragover.prevent @drop.prevent="onDropFile">
        <FileUp :size="22" aria-hidden="true" />
        <div class="dashboard__import-text">
          <p>把 <code class="code-text">.xml</code> 文件拖到这里，或点右侧按钮选择文件。</p>
          <p class="dashboard__import-hint">
            格式与 <code class="code-text">1箱3罐.XML</code> 相同（关联关系 Schema-3.0）。
            解析与结构校验在服务端完成：固定参数不符、层级未知、父子关系断裂一律拒绝并说明原因。
            导入<strong>只新建批次</strong>，不覆盖已有批次；批号重复时由你选择打开已有 / 创建新版本 / 取消。
          </p>
        </div>
        <input
          ref="fileInput"
          class="dashboard__file"
          type="file"
          accept=".xml,text/xml,application/xml"
          data-testid="import-xml-input"
          @change="onPickFile"
        />
        <AppButton variant="secondary" :disabled="batch.busy" @click="fileInput?.click()">
          <template #icon><FileUp :size="16" aria-hidden="true" /></template>
          选择 XML 文件
        </AppButton>
      </div>

      <p v-if="batch.importSummary" class="dashboard__import-ok" role="status" data-testid="import-summary">
        已导入 <strong>{{ batch.importSummary.sourceName || 'XML' }}</strong>：批号
        <span class="code-text">{{ batch.importSummary.batchNo }}</span> · 箱号
        <span class="code-text">{{ batch.importSummary.boxCode }}</span> ·
        {{ batch.importSummary.canCount }} 罐 / {{ batch.importSummary.particleTotal }} 粒 · 计划
        <span class="code-text">{{ batch.importSummary.plannedParticleCounts.join(' / ') }}</span>
      </p>
      <p v-if="batch.errorMessage" class="dashboard__import-error" role="alert">
        {{ batch.errorMessage }}
      </p>
      <ul v-if="batch.issues.length" class="dashboard__import-issues">
        <li v-for="issue in batch.issues" :key="`${issue.code}-${issue.field}`">
          <span class="code-text">{{ issue.field }}</span>：{{ issue.message }}
        </li>
      </ul>
    </AppCard>

    <AppBatchNoConflictDialog
      v-model="conflictOpen"
      :conflict="batch.conflict"
      :busy="batch.busy"
      @open-existing="openConflictExisting"
      @create-new-version="createNewVersionFromImport"
      @cancel="batch.dismissConflict()"
    />

    <AppCard
      title="已保存批次"
      subtitle="保存在本地 SQLite 库中，重启进程后仍然存在。"
    >
      <table v-if="batch.savedBatches.length" class="dashboard__table">
        <thead>
          <tr>
            <th>批号</th>
            <th>状态</th>
            <th>生产日期</th>
            <th>罐 / 粒子</th>
            <th>最后更新</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in batch.savedBatches" :key="item.id">
            <td class="code-text">{{ item.batchNo }}</td>
            <td><AppStatusBadge :tone="(item.status as never)" :label="item.statusLabel" /></td>
            <td class="code-text">{{ item.madeDate }}</td>
            <td class="code-text">{{ item.canCount }} / {{ item.actualParticleTotal }}</td>
            <td class="code-text dashboard__updated">{{ item.updatedAt }}</td>
            <td>
              <AppButton variant="ghost" @click="batch.openExisting(item.id)">
                <template #icon><FolderOpen :size="16" aria-hidden="true" /></template>
                打开
              </AppButton>
            </td>
          </tr>
        </tbody>
      </table>

      <AppEmpty
        v-else
        title="还没有已保存的批次"
        description="创建第一个批次开始扫码采集。批次会保存到本地数据库，重启后仍然存在。"
      >
        <RouterLink to="/base-info"><AppButton variant="primary">创建批次</AppButton></RouterLink>
      </AppEmpty>
    </AppCard>

    <section class="dashboard__legend">
      <TrendingUp :size="16" aria-hidden="true" />
      <p>
        状态一律使用「颜色 + 图标 + 文字」三重表达，颜色永不作为唯一信息载体——
        车间光照与个体视觉差异都不能影响判断。
      </p>
    </section>
  </div>
</template>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.dashboard__grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr);
  gap: var(--space-5);
}

.dashboard__import {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4);
  background: var(--color-surface-alt);
  border: 1px dashed var(--color-border-strong);
  border-radius: var(--radius-md);
}

.dashboard__import-text {
  flex: 1;
  min-width: 0;
}

.dashboard__import-text p {
  margin: 0;
}

.dashboard__import-hint {
  margin-top: var(--space-1) !important;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

/* 用按钮触发文件选择；input 本身不占位，但仍可被测试直接设定文件 */
.dashboard__file {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  border: 0;
}

.dashboard__import-ok {
  margin: var(--space-4) 0 0;
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-success, #15803d);
  background: var(--color-success-soft, #e6f4ea);
  border: 1px solid var(--color-success-border, #a8d5b5);
  border-radius: var(--radius-md);
}

.dashboard__import-error {
  margin: var(--space-4) 0 0;
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-danger);
  background: var(--color-danger-soft);
  border: 1px solid var(--color-danger-border);
  border-radius: var(--radius-md);
}

.dashboard__import-issues {
  margin: var(--space-3) 0 0;
  padding-left: var(--space-5);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

@media (max-width: 1100px) {
  .dashboard__grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

.dashboard__facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--space-4);
  margin: 0;
}

.dashboard__facts dt {
  font-size: var(--text-xs);
  color: var(--color-text-subtle);
}

.dashboard__facts dd {
  margin: var(--space-1) 0 0;
  font-size: var(--text-lg);
  font-weight: var(--weight-medium);
}

.dashboard__progress {
  margin-top: var(--space-5);
}

.dashboard__limit {
  margin-top: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.dashboard__checks {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  margin: 0;
  padding: 0;
  list-style: none;
}

.dashboard__checks li {
  display: flex;
  gap: var(--space-3);
  align-items: flex-start;
}

.dashboard__check-title {
  font-weight: var(--weight-medium);
}

.dashboard__check-detail {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.dashboard__golden {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: var(--space-4) 0 0;
  padding: var(--space-3) 0 0;
  list-style: none;
  border-top: 1px solid var(--color-border);
}

.dashboard__golden li {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
}

.dashboard__hash {
  margin-left: auto;
  color: var(--color-text-subtle);
}

.ok {
  color: var(--color-success);
}

.bad {
  color: var(--color-danger);
}

.dashboard__table {
  margin: calc(var(--space-2) * -1);
}

.dashboard__updated {
  font-size: var(--text-xs);
  color: var(--color-text-subtle);
}

.dashboard__legend {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  background: var(--color-surface-alt);
  border: 1px dashed var(--color-border-strong);
  border-radius: var(--radius-md);
}
</style>

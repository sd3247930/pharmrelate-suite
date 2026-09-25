<script setup lang="ts">
import { FileCheck2, ScanLine, ShieldAlert, ShieldCheck, TrendingUp } from 'lucide-vue-next';
import { computed } from 'vue';
import { RouterLink } from 'vue-router';

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

const hasDraft = computed(() => batch.batchNo.trim().length > 0);

const nextStep = computed(() => {
  if (!hasDraft.value) return { to: '/base-info', label: '开始创建批次' };
  if (batch.plannedParticleTotal < 1) return { to: '/package-structure', label: '设置包装结构' };
  return { to: '/preview', label: '生成 XML 预览' };
});
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

    <AppCard title="最近批次" subtitle="阶段 1 尚未接入本地数据库，暂无历史记录。">
      <AppEmpty
        title="还没有已保存的批次"
        description="创建第一个批次开始扫码采集。阶段 2 接入 SQLite 后这里会显示历史批次列表。"
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

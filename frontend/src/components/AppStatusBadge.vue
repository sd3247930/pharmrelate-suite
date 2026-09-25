<script setup lang="ts">
import {
  AlertCircle,
  Archive,
  Ban,
  CheckCircle2,
  CircleDashed,
  Download,
  GitMerge,
  Loader,
  Lock,
  WifiOff,
  type LucideIcon,
} from 'lucide-vue-next';
import { computed } from 'vue';

/**
 * 状态徽章 —— 强制"颜色 + 图标 + 文字"三重表达。
 *
 * 车间存在视觉识别差异，颜色永不作为唯一信息载体；图标也不是唯一载体，
 * 文字标签始终显示。这是本项目最核心的可用性约束之一。
 */
export type StatusTone =
  | 'draft'
  | 'collecting'
  | 'pending'
  | 'verified'
  | 'exported'
  | 'locked'
  | 'archived'
  | 'void'
  | 'offline'
  | 'conflict';

const props = defineProps<{
  /**
   * 可以直接传生命周期状态（draft / pending_review / …），也可以传视觉 tone。
   *
   * 之所以允许两种：调用方手里拿到的通常是后端返回的状态字符串，
   * 强制每个页面各自做一次映射，只要漏一个就会出现"未知状态"甚至渲染崩溃
   * （pending_review 与 pending 不同名，正是这个坑）。映射集中放在这里，
   * 是唯一不会漏的方式。
   */
  tone: StatusTone | string;
  label?: string;
  detail?: string;
}>();

interface ToneSpec {
  icon: LucideIcon;
  label: string;
}

const TONES: Record<StatusTone, ToneSpec> = {
  draft: { icon: CircleDashed, label: '草稿' },
  collecting: { icon: Loader, label: '采集中' },
  pending: { icon: AlertCircle, label: '待核对' },
  verified: { icon: CheckCircle2, label: '已核对' },
  exported: { icon: Download, label: '已导出' },
  locked: { icon: Lock, label: '已锁定' },
  archived: { icon: Archive, label: '已归档' },
  void: { icon: Ban, label: '已作废' },
  offline: { icon: WifiOff, label: '离线' },
  conflict: { icon: GitMerge, label: '冲突' },
};

/** 后端生命周期状态 → 视觉 tone。 */
const STATUS_TO_TONE: Record<string, StatusTone> = {
  draft: 'draft',
  collecting: 'collecting',
  pending_review: 'pending',
  verified: 'verified',
  exported: 'exported',
  locked: 'locked',
  archived: 'archived',
  void: 'void',
  offline: 'offline',
  conflict: 'conflict',
};

/** 兜底：遇到未知状态也要能渲染，绝不能因为一个没映射的值让整页白屏。 */
const UNKNOWN: ToneSpec = { icon: AlertCircle, label: '未知状态' };

const spec = computed<ToneSpec>(() => {
  const raw = String(props.tone);
  const tone = STATUS_TO_TONE[raw] ?? (raw as StatusTone);
  return TONES[tone] ?? UNKNOWN;
});
const toneClass = computed(() => {
  const raw = String(props.tone);
  const tone = STATUS_TO_TONE[raw] ?? (raw as StatusTone);
  return TONES[tone] ? tone : 'draft';
});
const text = computed(() => props.label ?? spec.value.label);
</script>

<template>
  <span class="app-status-badge" :class="`app-status-badge--${toneClass}`">
    <component :is="spec.icon" :size="14" aria-hidden="true" />
    <span class="app-status-badge__text">{{ text }}</span>
    <span v-if="detail" class="app-status-badge__detail">{{ detail }}</span>
  </span>
</template>

<style scoped>
.app-status-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 2px var(--space-3);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  line-height: 1.7;
  border: 1px solid;
  border-radius: var(--radius-pill);
  white-space: nowrap;
}

.app-status-badge__detail {
  font-weight: var(--weight-normal);
  opacity: 0.85;
}

.app-status-badge--draft,
.app-status-badge--archived {
  color: var(--color-neutral);
  background: var(--color-neutral-soft);
  border-color: var(--color-neutral-border);
}

.app-status-badge--collecting {
  color: var(--color-info);
  background: var(--color-info-soft);
  border-color: var(--color-info-border);
}

.app-status-badge--pending {
  color: var(--color-warning);
  background: var(--color-warning-soft);
  border-color: var(--color-warning-border);
}

.app-status-badge--verified,
.app-status-badge--exported {
  color: var(--color-success);
  background: var(--color-success-soft);
  border-color: var(--color-success-border);
}

.app-status-badge--locked {
  color: var(--color-text);
  background: var(--color-surface-sunken);
  border-color: var(--color-border-strong);
}

.app-status-badge--void {
  color: var(--color-danger);
  background: var(--color-danger-soft);
  border-color: var(--color-danger-border);
}

.app-status-badge--offline {
  color: var(--color-neutral);
  background: var(--color-surface-sunken);
  border-color: var(--color-neutral-border);
}

.app-status-badge--conflict {
  color: var(--color-danger);
  background: var(--color-warning-soft);
  border-color: var(--color-danger-border);
}
</style>

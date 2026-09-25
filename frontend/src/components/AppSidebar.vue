<script setup lang="ts">
import {
  ClipboardList,
  Download,
  Home,
  PanelsTopLeft,
  ScanLine,
  Settings,
  Share2,
  Boxes,
  type LucideIcon,
} from 'lucide-vue-next';
import { computed } from 'vue';
import { RouterLink, useRoute } from 'vue-router';

/**
 * 左侧主导航。
 *
 * 规范：宽度 220～240px、支持折叠、图标只做辅助识别而不代替文字、
 * 当前页有明显 active 状态、不给每个菜单配不同颜色。
 * 二期功能以"二期"标签明确标注并禁用，不做假入口。
 */
const props = defineProps<{ collapsed: boolean }>();
const emit = defineEmits<{ toggle: [] }>();

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  phase2?: boolean;
}

const PRIMARY: NavItem[] = [
  { to: '/', label: '工作台', icon: Home },
  { to: '/base-info', label: '基础信息', icon: PanelsTopLeft },
  { to: '/package-structure', label: '包装结构', icon: Boxes },
  { to: '/scanning', label: '扫码采集', icon: ScanLine },
  { to: '/preview', label: '预览导出', icon: Download },
];

const PHASE2: NavItem[] = [
  { to: '/collaboration', label: '多端协同', icon: Share2, phase2: true },
  { to: '/audit', label: '审计日志', icon: ClipboardList, phase2: true },
  { to: '/settings', label: '系统设置', icon: Settings, phase2: true },
];

const route = useRoute();
const activePath = computed(() => route.path);

void props;
</script>

<template>
  <aside class="app-sidebar" :class="{ 'app-sidebar--collapsed': collapsed }">
    <div class="app-sidebar__brand">
      <span class="app-sidebar__mark" aria-hidden="true">籽</span>
      <span v-if="!collapsed" class="app-sidebar__name">
        籽关通
        <small>PharmRelate Multi</small>
      </span>
    </div>

    <nav class="app-sidebar__nav" aria-label="主导航">
      <p v-if="!collapsed" class="app-sidebar__group">采集流程</p>
      <RouterLink
        v-for="item in PRIMARY"
        :key="item.to"
        :to="item.to"
        class="app-sidebar__link"
        :class="{ 'is-active': activePath === item.to }"
        :title="collapsed ? item.label : undefined"
      >
        <component :is="item.icon" :size="18" aria-hidden="true" />
        <span v-if="!collapsed">{{ item.label }}</span>
      </RouterLink>

      <p v-if="!collapsed" class="app-sidebar__group">后续版本</p>
      <span
        v-for="item in PHASE2"
        :key="item.to"
        class="app-sidebar__link app-sidebar__link--disabled"
        :title="`${item.label}（二期实现）`"
        aria-disabled="true"
      >
        <component :is="item.icon" :size="18" aria-hidden="true" />
        <template v-if="!collapsed">
          <span>{{ item.label }}</span>
          <em class="app-sidebar__tag">二期</em>
        </template>
      </span>
    </nav>

    <button class="app-sidebar__toggle" type="button" @click="emit('toggle')">
      <PanelsTopLeft :size="16" aria-hidden="true" />
      <span v-if="!collapsed">收起导航</span>
      <span v-else class="sr-only">展开导航</span>
    </button>
  </aside>
</template>

<style scoped>
.app-sidebar {
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  width: var(--sidebar-width);
  padding: var(--space-4) var(--space-3);
  background: var(--color-surface);
  border-right: 1px solid var(--color-border);
  transition: width var(--duration-normal) var(--ease-out);
}

.app-sidebar--collapsed {
  width: var(--sidebar-width-collapsed);
  align-items: center;
}

.app-sidebar__brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 0 var(--space-2) var(--space-5);
}

.app-sidebar__mark {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  font-weight: var(--weight-bold);
  color: var(--color-text-inverse);
  background: var(--color-primary);
  border-radius: var(--radius-md);
}

.app-sidebar__name {
  display: flex;
  flex-direction: column;
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  line-height: 1.2;
}

.app-sidebar__name small {
  font-size: var(--text-xs);
  font-weight: var(--weight-normal);
  color: var(--color-text-subtle);
}

.app-sidebar__nav {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
}

.app-sidebar__group {
  padding: var(--space-4) var(--space-3) var(--space-1);
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  color: var(--color-text-subtle);
  letter-spacing: 0.04em;
}

.app-sidebar__link {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-height: var(--touch-target);
  padding: 0 var(--space-3);
  font-size: var(--text-base);
  color: var(--color-text-muted);
  text-decoration: none;
  border-radius: var(--radius-md);
  transition: background-color var(--duration-fast) var(--ease-out);
}

.app-sidebar__link:hover {
  color: var(--color-text);
  background: var(--color-surface-alt);
}

/* active 状态：背景 + 左侧色条 + 加粗，不只靠颜色 */
.app-sidebar__link.is-active {
  font-weight: var(--weight-semibold);
  color: var(--color-primary-strong);
  background: var(--color-primary-soft);
  box-shadow: inset 3px 0 0 var(--color-primary);
}

.app-sidebar__link--disabled {
  color: var(--color-text-subtle);
  cursor: not-allowed;
}

.app-sidebar__link--disabled:hover {
  color: var(--color-text-subtle);
  background: transparent;
}

.app-sidebar__tag {
  margin-left: auto;
  padding: 0 var(--space-2);
  font-size: var(--text-xs);
  font-style: normal;
  color: var(--color-text-subtle);
  background: var(--color-neutral-soft);
  border-radius: var(--radius-pill);
}

.app-sidebar__toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-height: var(--touch-target);
  margin-top: var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  background: transparent;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  cursor: pointer;
}

.app-sidebar__toggle:hover {
  background: var(--color-surface-alt);
}
</style>

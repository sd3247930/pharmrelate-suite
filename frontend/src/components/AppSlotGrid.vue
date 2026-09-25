<script setup lang="ts">
import { CheckCircle2, TriangleAlert } from 'lucide-vue-next';
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import { visibleRange, type Slot } from '../services/slotGrid';

/**
 * 虚拟化槽位网格。

 * 为什么必须虚拟化：单批次上限 12500 个槽位，一次性铺成 DOM 会创建上万个节点，
 * 滚动和扫码都会明显卡顿（V1.1 44 章明确禁止）。
 * 这里每帧最多渲染"视口内 + 少量 overscan"的槽位，通常只有百来个节点。

 * 交互与渲染是分开的：槽位数组怎么来的、怎么算视口窗口，全部在
 * `services/slotGrid.ts` 里（纯函数，不依赖 DOM）；这个组件只负责把结果画出来。
 * 阶段 3.4 的删除/替换/选中因此不需要为虚拟化改一行。
 */
const props = withDefaults(
  defineProps<{
    slots: Slot[];
    /** 单个槽位的最小宽度，用于按容器宽度算列数。 */
    minSlotWidth?: number;
    rowHeight?: number;
    /** 视口高度。 */
    height?: number;
    selectedIndex?: number | null;
  }>(),
  {
    minSlotWidth: 64,
    rowHeight: 30,
    height: 240,
    selectedIndex: null,
  },
);

const emit = defineEmits<{ select: [slot: Slot] }>();

const scroller = ref<HTMLElement | null>(null);
const scrollTop = ref(0);
const containerWidth = ref(props.minSlotWidth * 4);
let observer: ResizeObserver | undefined;

const columns = computed(() =>
  Math.max(1, Math.floor(containerWidth.value / props.minSlotWidth)),
);

const geometry = computed(() => ({
  columns: columns.value,
  rowHeight: props.rowHeight,
  viewportHeight: props.height,
  overscanRows: 2,
}));

const range = computed(() =>
  visibleRange(props.slots.length, scrollTop.value, geometry.value),
);

/** 只渲染视口内的这一段。这是"不卡顿"的全部秘密。 */
const visibleSlots = computed(() => props.slots.slice(range.value.startIndex, range.value.endIndex));

const gridStyle = computed(() => ({
  height: `${range.value.totalHeight}px`,
}));

const rowStyle = computed(() => ({
  transform: `translateY(${range.value.offsetY}px)`,
  gridTemplateColumns: `repeat(${columns.value}, minmax(0, 1fr))`,
}));

function onScroll(event: Event): void {
  scrollTop.value = (event.target as HTMLElement).scrollTop;
}

/**
 * 按条码定位并滚动过去。

 * 重复扫码被拒绝时，界面要能把操作员直接带到那个槽位，
 * 而不是只说一句"条码已使用"。
 */
function scrollToIndex(index: number): void {
  const element = scroller.value;
  if (!element || index < 0) return;
  const row = Math.floor(index / columns.value);
  const target = row * props.rowHeight;
  element.scrollTop = Math.max(0, target - props.rowHeight);
  scrollTop.value = element.scrollTop;
}

defineExpose({ scrollToIndex });

onMounted(() => {
  const element = scroller.value;
  if (!element) return;
  containerWidth.value = element.clientWidth || containerWidth.value;
  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width) containerWidth.value = width;
    });
    observer.observe(element);
  }
});

onBeforeUnmount(() => observer?.disconnect());

// 槽位总数变化（例如换了罐）时回到顶部，避免停留在越界的滚动位置
watch(
  () => props.slots.length,
  () => {
    if (scroller.value) {
      scroller.value.scrollTop = 0;
      scrollTop.value = 0;
    }
  },
);
</script>

<template>
  <div
    ref="scroller"
    class="slot-grid"
    :style="{ height: `${height}px` }"
    role="list"
    :aria-rowcount="slots.length"
    @scroll="onScroll"
  >
    <div class="slot-grid__canvas" :style="gridStyle">
      <div class="slot-grid__row" :style="rowStyle">
        <button
          v-for="slot in visibleSlots"
          :key="`${slot.canIndex}-${slot.index}`"
          type="button"
          role="listitem"
          class="slot-grid__slot"
          :class="[
            `is-${slot.status}`,
            { 'is-selected': selectedIndex === slot.index },
          ]"
          :title="slot.code ?? '空槽'"
          :aria-label="`槽位 ${slot.index}，${slot.status === 'scanned' ? '已扫描' : slot.status === 'empty' ? '待扫描' : '异常'}${slot.code ? '，条码 ' + slot.code : ''}`"
          @click="emit('select', slot)"
        >
          <span class="code-text">{{ String(slot.index).padStart(4, '0') }}</span>
          <CheckCircle2 v-if="slot.status === 'scanned'" :size="12" aria-hidden="true" />
          <TriangleAlert v-else-if="slot.status === 'conflict'" :size="12" aria-hidden="true" />
          <span v-else class="slot-grid__empty" aria-hidden="true">○</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.slot-grid {
  position: relative;
  overflow-y: auto;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  /* 滚动时不要触发父级重排 */
  contain: strict;
}

.slot-grid__canvas {
  position: relative;
  width: 100%;
}

.slot-grid__row {
  position: absolute;
  top: 0;
  left: 0;
  display: grid;
  gap: 2px;
  width: 100%;
  padding: 0 var(--space-2);
  will-change: transform;
}

.slot-grid__slot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 2px;
  height: 28px;
  padding: 0 var(--space-2);
  font-size: var(--text-xs);
  background: var(--color-surface-alt);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  cursor: pointer;
}

/* 状态三重表达：颜色 + 图形 + 序号，颜色不是唯一线索 */
.slot-grid__slot.is-scanned {
  color: var(--color-success);
  background: var(--color-success-soft);
  border-color: var(--color-success-border);
}

.slot-grid__slot.is-empty {
  color: var(--color-text-subtle);
}

.slot-grid__slot.is-conflict {
  color: var(--color-danger);
  background: var(--color-danger-soft);
  border-color: var(--color-danger-border);
}

.slot-grid__slot.is-selected {
  font-weight: var(--weight-semibold);
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

.slot-grid__empty {
  color: var(--color-text-subtle);
}
</style>

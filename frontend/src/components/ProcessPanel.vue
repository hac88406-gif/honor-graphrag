<script setup>
import { computed } from 'vue'

import { NODE_LABELS } from '../api.js'

// 过程展示（1.6 第 4 条：Agent 执行过程指示 —— 当前在跑哪个节点）。
// 只展示**已发生**的节点（来自 node_start 事件），不预测后续节点：
// 预测会让「实际没跑」看起来像「跑过了」，正是本项目一直在防的静默失败。
const props = defineProps({
  nodes: { type: Array, default: () => [] },
  running: { type: Boolean, default: false },
})

const items = computed(() =>
  props.nodes.map((name, i) => ({
    name,
    label: NODE_LABELS[name] || name,
    // 只有「还在跑且是最后一个」才显示为进行中，其余视为已完成
    current: props.running && i === props.nodes.length - 1,
  })),
)
</script>

<template>
  <div v-if="items.length" class="process">
    <span class="process-title">执行过程</span>
    <ul class="process-list">
      <li
        v-for="(it, i) in items"
        :key="`${it.name}-${i}`"
        class="process-item"
        :class="{ 'is-current': it.current, 'is-done': !it.current }"
      >
        <span class="dot" aria-hidden="true"></span>
        <span class="label">{{ it.label }}</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.process {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
  padding: 8px 10px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 10px;
}
.process-title {
  font-size: 12px;
  color: var(--text-3);
  line-height: 20px;
  flex: none;
}
.process-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  list-style: none;
  margin: 0;
  padding: 0;
}
.process-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  line-height: 20px;
  color: var(--text-3);
}
.process-item .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--border-strong);
}
.process-item.is-done .dot {
  background: var(--primary);
}
.process-item.is-done .label {
  color: var(--text-2);
}
.process-item.is-current .label {
  color: var(--primary);
  font-weight: 600;
}
/* 当前节点用「实心点 + 描边环」区分，**不做动画** —— 1.6 明确排除「动画特效」 */
.process-item.is-current .dot {
  background: var(--primary);
  box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.18);
}
</style>

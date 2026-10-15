<script setup>
import { computed } from 'vue'

// 来源卡片（1.6 第 3 条：每条回答下方的来源卡片 —— 英雄/关系来自图谱，还是哪篇攻略文本 + 版本）。
// 用原生 <details> 实现「可展开」，不引 UI 库。
//
// citation 与 evidence 按下标配对（后端 `_citation` 用 1-based evidence 序号做 index），
// 展开后展示 evidence 原文，让「可追溯」落到实处而不是只给一个标题。
const props = defineProps({
  citations: { type: Array, default: () => [] },
  evidence: { type: Array, default: () => [] },
})

const rows = computed(() =>
  props.citations.map((c) => ({
    ...c,
    kindLabel: c.kind === 'graph' ? '图谱' : '攻略文本',
    content: props.evidence[c.index - 1]?.content || '',
  })),
)
</script>

<template>
  <div v-if="rows.length" class="sources">
    <div class="sources-title">来源（{{ rows.length }}）</div>
    <details v-for="row in rows" :key="row.index" class="source">
      <summary class="source-summary">
        <span class="tag" :class="`tag-${row.kind}`">{{ row.kindLabel }}</span>
        <span class="source-label">{{ row.label }}</span>
        <span v-if="row.patch" class="patch">{{ row.patch }}</span>
      </summary>
      <div class="source-body">
        <p v-if="row.content" class="content">{{ row.content }}</p>
        <a v-if="row.url" :href="row.url" target="_blank" rel="noreferrer" class="url">{{ row.url }}</a>
        <p v-else class="url muted">该来源未提供原文链接</p>
      </div>
    </details>
  </div>
</template>

<style scoped>
.sources {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--border);
}
.sources-title {
  font-size: 12px;
  color: var(--text-3);
  margin-bottom: 6px;
}
.source {
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
  margin-bottom: 6px;
  overflow: hidden;
}
.source-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  cursor: pointer;
  list-style: none;
  font-size: 13px;
}
.source-summary::-webkit-details-marker {
  display: none;
}
.source-summary:hover {
  background: var(--surface-2);
}
.tag {
  flex: none;
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid transparent;
}
.tag-graph {
  color: var(--primary);
  background: var(--primary-weak);
  border-color: var(--primary-weak-border);
}
.tag-vector {
  color: var(--accent-cyan);
  background: var(--cyan-weak);
  border-color: var(--cyan-weak-border);
}
.source-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-1);
}
.patch {
  flex: none;
  font-size: 11px;
  color: var(--text-3);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0 6px;
}
.source-body {
  padding: 8px 10px 10px;
  border-top: 1px solid var(--border);
  background: var(--surface-2);
}
.content {
  margin: 0 0 6px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
}
.url {
  font-size: 12px;
  color: var(--accent-cyan);
  word-break: break-all;
}
.muted {
  color: var(--text-3);
  margin: 0;
}
</style>

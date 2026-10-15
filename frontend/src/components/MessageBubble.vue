<script setup>
import { computed } from 'vue'

import ProcessPanel from './ProcessPanel.vue'
import SourceCards from './SourceCards.vue'

// 单条消息。用户消息只显示文本；助手消息按 `done.type` **差异化渲染**
// （1.6 第 5 条：拒答 / 澄清反问的差异化展示 —— 不能看起来和正常回答一样）。
const props = defineProps({
  message: { type: Object, required: true },
})
const emit = defineEmits(['pick'])

const m = computed(() => props.message)
const isUser = computed(() => m.value.role === 'user')
const done = computed(() => m.value.done || null)

// 5.1 的 type 枚举 -> 展示档位。answer 不加任何标记（正常回答不该有额外视觉噪音）。
const variant = computed(() => {
  const t = done.value?.type
  if (t === 'reject') return 'reject'
  if (t === 'clarify') return 'clarify'
  if (t === 'low_confidence') return 'low'
  return 'answer'
})

const badge = computed(() => {
  if (variant.value === 'reject') return '拒答'
  if (variant.value === 'clarify') return '需要澄清'
  if (variant.value === 'low') return '依据较少'
  return ''
})

const confidenceText = computed(() => {
  if (!done.value || done.value.confidence === undefined || done.value.confidence === null) return ''
  if (variant.value !== 'answer') return ''
  return `置信度 ${Number(done.value.confidence).toFixed(2)}`
})
</script>

<template>
  <div class="row" :class="isUser ? 'row-user' : 'row-assistant'">
    <div v-if="isUser" class="bubble bubble-user">{{ m.text }}</div>

    <div v-else class="bubble bubble-assistant" :class="`variant-${variant}`">
      <div v-if="badge" class="badge" :class="`badge-${variant}`">{{ badge }}</div>

      <ProcessPanel :nodes="m.nodes" :running="m.pending" />

      <p v-if="m.thinking && !m.answer" class="thinking">正在思考…</p>

      <p v-if="m.answer" class="answer">{{ m.answer }}</p>

      <!-- 澄清：候选渲染成可点选的追问，点了直接填入输入框（1.6 的差异化展示） -->
      <div v-if="variant === 'clarify' && done?.clarify_options?.length" class="options">
        <button
          v-for="opt in done.clarify_options"
          :key="opt"
          type="button"
          class="option"
          @click="emit('pick', opt)"
        >
          {{ opt }}
        </button>
      </div>

      <p v-if="m.error" class="error">{{ m.error }}</p>

      <div class="meta">
        <span v-if="confidenceText" class="meta-item">{{ confidenceText }}</span>
        <span v-if="done?.fallback" class="meta-item warn" title="模型生成未采用，回落到确定性证据组装">
          确定性组装
        </span>
        <span v-if="m.pending" class="meta-item">生成中…</span>
      </div>

      <SourceCards :citations="m.citations" :evidence="m.evidence" />
    </div>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  margin-bottom: 16px;
}
.row-user {
  justify-content: flex-end;
}
.row-assistant {
  justify-content: flex-start;
}
.bubble {
  max-width: 78%;
  border-radius: 14px;
  padding: 12px 14px;
  font-size: 14px;
  line-height: 1.75;
  word-break: break-word;
}
.bubble-user {
  background: var(--primary);
  color: #fff;
  border-bottom-right-radius: 4px;
  white-space: pre-wrap;
}
.bubble-assistant {
  background: var(--surface);
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
  border-bottom-left-radius: 4px;
}
/* 差异化：拒答偏中性灰，澄清偏琥珀（需要用户动作），低置信偏提示色 */
.bubble-assistant.variant-reject {
  border-color: var(--border-strong);
  background: var(--surface-3);
}
.bubble-assistant.variant-clarify {
  border-color: var(--amber-weak-border);
  background: var(--amber-weak);
}
.bubble-assistant.variant-low {
  border-color: var(--amber-weak-border);
}
.badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 1px 8px;
  border-radius: 999px;
  margin-bottom: 8px;
}
.badge-reject {
  color: var(--text-2);
  background: var(--surface);
  border: 1px solid var(--border-strong);
}
.badge-clarify,
.badge-low {
  color: #b45309;
  background: #fff;
  border: 1px solid var(--amber-weak-border);
}
.thinking {
  color: var(--text-3);
  font-style: italic;
  margin: 0 0 8px;
}
.answer {
  margin: 0;
  white-space: pre-wrap;
  color: var(--text-1);
}
.options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}
.option {
  font: inherit;
  font-size: 13px;
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid var(--primary-weak-border);
  background: var(--surface);
  color: var(--primary);
  cursor: pointer;
}
.option:hover {
  background: var(--primary-weak);
}
.error {
  margin: 8px 0 0;
  color: var(--danger);
  font-size: 13px;
}
.meta {
  display: flex;
  gap: 10px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-3);
}
.meta-item.warn {
  color: #b45309;
}
</style>

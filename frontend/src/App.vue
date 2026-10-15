<script setup>
import { nextTick, onMounted, reactive, ref } from 'vue'

import { askStream, fetchHealth, getSessionId } from './api.js'
import Composer from './components/Composer.vue'
import MessageBubble from './components/MessageBubble.vue'

// 最简聊天页（规格书 1.6 边界）：消息列表 + 输入框 + 来源卡片 + 过程展示 + 拒答/澄清差异化。
// 明确不做：登录 / 历史会话管理 / 设置 / 主题切换 / 移动端适配 / 动画特效。
//
// 状态全在组件内（ref/reactive），**不引 Pinia**：单页只有一个会话，引入状态库只是把
// 一个 ref 换成 store + actions，没有任何收益（9.2「最简依赖」）。
const sessionId = getSessionId()
const messages = ref([])
const input = ref('')
const busy = ref(false)
const health = ref(null)
const healthError = ref('')
const scroller = ref(null)

onMounted(async () => {
  try {
    health.value = await fetchHealth()
  } catch (e) {
    healthError.value = e.message || String(e)
  }
})

async function scrollToEnd() {
  await nextTick()
  const el = scroller.value
  if (el) el.scrollTop = el.scrollHeight
}

function handleEvent(a, { event, data }) {
  if (event === 'node_start') {
    // 去重：同一节点在一轮里只应推一次（若后端将来重推，前端也不该画两遍）
    if (!a.nodes.includes(data.node)) a.nodes.push(data.node)
  } else if (event === 'thinking') {
    a.thinking = true
  } else if (event === 'evidence') {
    a.evidence.push(data.evidence)
  } else if (event === 'token') {
    a.answer += data.text
    scrollToEnd()
  } else if (event === 'citation') {
    a.citations = data.citations || []
  } else if (event === 'done') {
    a.done = data
    a.thinking = false
  } else if (event === 'error') {
    a.error = data.message || '服务异常'
    a.thinking = false
  }
}

async function send() {
  const question = input.value.trim()
  if (!question || busy.value) return

  messages.value.push({ role: 'user', text: question })
  // reactive：后续在回调里按字段改，Vue 才能追踪到（往 ref 数组里塞裸对象后改裸对象不会触发更新）
  const assistant = reactive({
    role: 'assistant',
    answer: '',
    nodes: [],
    evidence: [],
    citations: [],
    done: null,
    error: '',
    thinking: false,
    pending: true,
  })
  messages.value.push(assistant)
  input.value = ''
  busy.value = true
  await scrollToEnd()

  try {
    await askStream({ sessionId, question, onEvent: (ev) => handleEvent(assistant, ev) })
  } catch (e) {
    assistant.error = e.message || String(e)
  } finally {
    assistant.pending = false
    assistant.thinking = false
    busy.value = false
    await scrollToEnd()
  }
}

function pickOption(text) {
  input.value = text
}
</script>

<template>
  <div class="app">
    <header class="header">
      <div class="brand">
        <span class="logo" aria-hidden="true">王</span>
        <div>
          <h1 class="title">王者荣耀 GraphRAG 问答</h1>
          <p class="subtitle">图谱关系 + 攻略文本，答案可追溯到来源</p>
        </div>
      </div>
      <div class="health">
        <template v-if="health">
          <span class="chip" :class="health.neo4j?.ok ? 'ok' : 'bad'" :title="health.neo4j?.detail">Neo4j</span>
          <span class="chip" :class="health.chroma?.ok ? 'ok' : 'bad'" :title="health.chroma?.detail">Chroma</span>
          <span class="chip" :class="health.llm?.ok ? 'ok' : 'bad'" :title="health.llm?.detail">LLM</span>
        </template>
        <span v-else-if="healthError" class="chip bad">后端未连通</span>
      </div>
    </header>

    <main ref="scroller" class="scroller">
      <div v-if="!messages.length" class="empty">
        <p class="empty-title">试试这样问</p>
        <ul class="empty-list">
          <li>铠被谁克制？</li>
          <li>貂蝉的铭文怎么搭配？</li>
          <li>上官婉儿为什么克制高渐离？</li>
          <li>亚瑟怎么出装？</li>
        </ul>
      </div>

      <MessageBubble
        v-for="(m, i) in messages"
        :key="i"
        :message="m"
        @pick="pickOption"
      />
    </main>

    <footer class="footer">
      <p v-if="healthError" class="banner">
        无法连接后端（{{ healthError }}）。请先启动 uvicorn（见 README），前端通过 /api 代理访问。
      </p>
      <Composer v-model="input" :disabled="busy" @submit="send" />
    </footer>
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  max-width: 960px;
  margin: 0 auto;
  background: var(--surface-2);
  border-left: 1px solid var(--border);
  border-right: 1px solid var(--border);
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 18px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}
.logo {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: var(--primary);
  color: #fff;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}
.title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-1);
}
.subtitle {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--text-3);
}
.health {
  display: flex;
  gap: 6px;
}
.chip {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--border);
  color: var(--text-3);
  background: var(--surface-2);
}
.chip.ok {
  color: var(--primary);
  border-color: var(--primary-weak-border);
  background: var(--primary-weak);
}
.chip.bad {
  color: var(--danger);
  border-color: #fecaca;
  background: #fef2f2;
}
.scroller {
  flex: 1;
  overflow-y: auto;
  padding: 18px;
}
.empty {
  color: var(--text-3);
  font-size: 13px;
  margin-top: 24px;
}
.empty-title {
  margin: 0 0 8px;
}
.empty-list {
  margin: 0;
  padding-left: 18px;
  line-height: 2;
}
.footer {
  background: var(--surface);
}
.banner {
  margin: 0;
  padding: 8px 14px;
  font-size: 12px;
  color: var(--danger);
  background: #fef2f2;
  border-top: 1px solid #fecaca;
}
</style>

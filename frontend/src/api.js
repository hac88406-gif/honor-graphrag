// 与后端的全部网络交互（5.2 / 5.3）。
//
// **为什么流式用 fetch + ReadableStream，而不是 EventSource**（M5 决策，见 DECISIONS）：
// 浏览器原生 `EventSource` **只能发 GET**，而 5.2 把问答定义为 `POST /api/chat`
// （问题体带 session_id + question，还可能是长文本）。用 EventSource 就得把问题塞进
// query string 并另开一个 GET 端点，等于为了一个客户端类去改服务端契约。
// `fetch` + `resp.body.getReader()` 是原生能力，能发 POST，也能逐帧读 SSE —— 规格书
// 1.6 要求的「原生 fetch」这一半足够，EventSource 那一半在 POST 语义下用不上。

// 5.3 节点名 -> 面向用户的过程说明（过程展示用）
export const NODE_LABELS = {
  entity_linking: '实体链接',
  intent_routing: '意图识别',
  graph_query: '图谱查询',
  vector_search: '向量检索',
  fuse: '证据融合',
  confidence: '置信度判定',
  generate: '答案生成',
  clarify: '澄清反问',
  reject: '拒答判定',
  memory: '记忆更新',
}

export const NODE_ORDER = [
  'entity_linking', 'intent_routing', 'graph_query', 'vector_search',
  'fuse', 'confidence', 'generate', 'clarify', 'reject', 'memory',
]

// 每个标签页一个会话 id：刷新保留上下文（sessionStorage），关掉标签即清空。
// 1.6 明确不做「历史会话管理页」，所以不需要跨标签共享或持久化到 localStorage。
export function getSessionId() {
  let sid = sessionStorage.getItem('hg_session_id')
  if (!sid) {
    sid = (crypto.randomUUID && crypto.randomUUID()) || `s-${Date.now()}`
    sessionStorage.setItem('hg_session_id', sid)
  }
  return sid
}

function parseFrame(frame) {
  let name = null
  let data = null
  for (const line of frame.split('\n')) {
    if (line.startsWith('event: ')) name = line.slice(7).trim()
    else if (line.startsWith('data: ')) data = line.slice(6)
  }
  if (!name || data === null) return null
  try {
    return { event: name, data: JSON.parse(data) }
  } catch {
    return null // 单帧解析失败不该让整轮回答断掉
  }
}

// 逐帧回调 onEvent({event, data})。返回 Promise，流结束或出错时 resolve/reject。
export async function askStream({ sessionId, question, onEvent, signal }) {
  const resp = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, question, stream: true }),
    signal,
  })
  if (!resp.ok) throw new Error(`服务返回 HTTP ${resp.status}`)
  if (!resp.body) throw new Error('响应没有可读流（浏览器不支持流式读取？）')

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buf = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    // 某些代理/平台会把 \n 换成 \r\n，先归一化，否则分帧会错位
    buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
    let idx
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const frame = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      const ev = parseFrame(frame)
      if (ev) onEvent(ev)
    }
  }
}

export async function fetchHealth() {
  const resp = await fetch('/api/health')
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json()
}

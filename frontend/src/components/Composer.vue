<script setup>
// 输入框 + 发送（1.6 第 2 条）。Enter 发送、Shift+Enter 换行。
const props = defineProps({
  modelValue: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'submit'])

function onInput(e) {
  emit('update:modelValue', e.target.value)
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    emit('submit')
  }
}
</script>

<template>
  <div class="composer">
    <textarea
      class="input"
      :value="modelValue"
      :disabled="disabled"
      rows="1"
      placeholder="问点什么，比如「铠被谁克制」「貂蝉的铭文怎么搭配」"
      @input="onInput"
      @keydown="onKeydown"
    ></textarea>
    <button class="send" type="button" :disabled="disabled || !modelValue.trim()" @click="emit('submit')">
      {{ disabled ? '生成中…' : '发送' }}
    </button>
  </div>
</template>

<style scoped>
.composer {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  padding: 12px;
  border-top: 1px solid var(--border);
  background: var(--surface);
}
.input {
  flex: 1;
  resize: none;
  max-height: 140px;
  min-height: 42px;
  padding: 10px 12px;
  font: inherit;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-1);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 10px;
  outline: none;
}
.input:focus {
  border-color: var(--primary);
  background: var(--surface);
}
.send {
  flex: none;
  height: 42px;
  padding: 0 20px;
  font: inherit;
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  background: var(--primary);
  border: none;
  border-radius: 10px;
  cursor: pointer;
}
.send:hover:not(:disabled) {
  background: var(--primary-strong);
}
.send:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>

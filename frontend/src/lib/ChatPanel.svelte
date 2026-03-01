<script>
  import { createEventDispatcher } from 'svelte';
  import { tick } from 'svelte';

  export let workspaceId = 'local_dev';
  export let contextNode = null;

  const dispatch = createEventDispatcher();
  const API = 'http://localhost:8000';

  let messages = [];
  let input = '';
  let loading = false;
  let messagesEl;

  async function send() {
    const text = input.trim();
    if (!text || loading) return;
    input = '';

    messages = [...messages, { role: 'user', content: text }];
    loading = true;
    await scrollBottom();

    try {
      const res = await fetch(`${API}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          workspace_id: workspaceId,
          context_node_id: contextNode?.id || null,
        }),
      });

      const data = await res.json();
      messages = [...messages, {
        role: 'assistant',
        content: data.answer,
        evidence: data.evidence,
        cypher: data.cypher_used,
        tools: data.tools_called,
        latency: data.latency_ms,
        highlight: data.highlight_node_ids || [],
        hasMermaid: !!(data.mermaid),
      }];

      if (data.highlight_node_ids?.length) {
        dispatch('highlight', data.highlight_node_ids);
      }
      if (data.mermaid) {
        dispatch('mermaid', data.mermaid);
      }
    } catch(e) {
      messages = [...messages, { role: 'assistant', content: `Error: ${e.message}`, error: true }];
    }

    loading = false;
    await scrollBottom();
  }

  async function scrollBottom() {
    await tick();
    if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function handleKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  function clearContext() {
    dispatch('clearContext');
  }

  const SUGGESTED = [
    'What would break if I deleted this file?',
    'Who owns this file?',
    'What does this function call?',
    'Are there circular imports?',
    'Which file has the most functions?',
  ];
</script>

<div class="chat-panel">
  <div class="chat-header">
    <span class="mono" style="font-size:11px;color:var(--text-1)">Chat</span>
    {#if contextNode}
      <div class="context-pill">
        <span>{contextNode.type}: {(contextNode.label || contextNode.id).split('/').pop()}</span>
        <button class="pill-close" on:click={clearContext}>✕</button>
      </div>
    {/if}
  </div>

  <div class="messages" bind:this={messagesEl}>
    {#if messages.length === 0}
      <div class="empty-state">
        <p class="dimmer mono" style="font-size:11px;margin-bottom:12px">Ask anything about the codebase</p>
        <div class="suggestions">
          {#each SUGGESTED as s}
            <button class="suggestion" on:click={() => { input = s; }}>{s}</button>
          {/each}
        </div>
      </div>
    {/if}

    {#each messages as msg}
      <div class="message {msg.role}" class:error={msg.error}>
        <div class="msg-role mono">{msg.role === 'user' ? 'you' : 'ai'}</div>
        <div class="msg-content">{msg.content}</div>
        {#if msg.hasMermaid}
          <div class="diagram-note">↗ Diagram rendered in graph view</div>
        {/if}
        {#if msg.highlight?.length}
          <div class="highlight-note">↗ {msg.highlight.length} node{msg.highlight.length > 1 ? 's' : ''} highlighted in graph</div>
        {/if}
        {#if msg.tools?.length}
          <div class="msg-meta mono">
            {msg.tools.join(' → ')} · {msg.latency}ms
          </div>
        {/if}
        {#if msg.cypher}
          <details class="cypher-block">
            <summary class="mono">cypher</summary>
            <pre>{msg.cypher}</pre>
          </details>
        {/if}
      </div>
    {/each}

    {#if loading}
      <div class="message assistant">
        <div class="msg-role mono">ai</div>
        <div class="typing">
          <span></span><span></span><span></span>
        </div>
      </div>
    {/if}
  </div>

  <div class="chat-input">
    <textarea
      bind:value={input}
      on:keydown={handleKey}
      placeholder="Ask about the codebase..."
      rows="2"
      disabled={loading}
    ></textarea>
    <button class="primary send-btn" on:click={send} disabled={loading || !input.trim()}>
      ↑
    </button>
  </div>
</div>

<style>
.chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg-0);
  overflow: hidden;
  min-height: 0;
}

.chat-header {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-1);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.context-pill {
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--accent-dim);
  border: 1px solid var(--accent);
  border-radius: 10px;
  padding: 1px 6px 1px 8px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--accent);
}
.pill-close {
  background: none;
  border: none;
  color: var(--accent);
  font-size: 10px;
  padding: 0 2px;
  cursor: pointer;
  line-height: 1;
}
.pill-close:hover { background: none; }

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
}

.empty-state {
  padding: 16px 0;
}

.suggestions {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.suggestion {
  text-align: left;
  font-size: 11px;
  padding: 4px 8px;
  background: transparent;
  border-color: var(--border);
  color: var(--text-1);
  white-space: normal;
  line-height: 1.4;
}
.suggestion:hover { color: var(--accent); border-color: var(--accent); background: var(--accent-dim); }

.message {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.msg-role {
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--text-2);
}
.message.user .msg-role { color: var(--accent); }
.message.error .msg-content { color: var(--err); }

.msg-content {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-0);
  white-space: pre-wrap;
  word-break: break-word;
}

.diagram-note {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--warn);
  margin-top: 4px;
}
.highlight-note {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--accent);
  margin-top: 2px;
}
.msg-meta {
  font-size: 10px;
  color: var(--text-2);
}

.cypher-block {
  margin-top: 4px;
}
.cypher-block summary {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-2);
  cursor: pointer;
  user-select: none;
}
.cypher-block summary:hover { color: var(--accent); }
.cypher-block pre {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--info);
  background: var(--bg-2);
  border: 1px solid var(--border);
  padding: 8px;
  margin-top: 4px;
  border-radius: var(--radius);
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.typing {
  display: flex;
  gap: 4px;
  align-items: center;
  padding: 4px 0;
}
.typing span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--text-2);
  animation: blink 1.2s infinite;
}
.typing span:nth-child(2) { animation-delay: 0.2s; }
.typing span:nth-child(3) { animation-delay: 0.4s; }
@keyframes blink {
  0%, 80%, 100% { opacity: 0.2; }
  40% { opacity: 1; }
}

.chat-input {
  padding: 10px 12px;
  border-top: 1px solid var(--border);
  background: var(--bg-1);
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.chat-input textarea {
  flex: 1;
  resize: none;
  font-size: 12px;
  line-height: 1.4;
  padding: 6px 8px;
}

.send-btn {
  padding: 0 12px;
  font-size: 16px;
  align-self: stretch;
}
</style>
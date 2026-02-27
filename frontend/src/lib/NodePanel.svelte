<script>
  import { createEventDispatcher, onMount } from 'svelte';
  export let node = null;
  export let workspaceId = 'local_dev';

  const dispatch = createEventDispatcher();
  const API = 'http://localhost:8000';

  let detail = null;
  let loading = false;

  $: if (node) loadDetail();

  async function loadDetail() {
    if (!node) return;
    loading = true;
    detail = null;
    try {
      const res = await fetch(`${API}/node/${encodeURIComponent(node.id)}?workspace_id=${workspaceId}&node_type=${node.type}`);
      if (res.ok) detail = await res.json();
    } catch(e) {}
    loading = false;
  }

  function shortPath(path) {
    if (!path) return '';
    const parts = path.split('/');
    return parts.slice(-2).join('/');
  }

  function typeColor(type) {
    const m = { File:'var(--col-file)', Function:'var(--col-function)', Class:'var(--col-class)', Author:'var(--col-author)', Commit:'var(--col-commit)' };
    return m[type] || 'var(--text-1)';
  }
</script>

<div class="panel">
  <div class="panel-header">
    <span class="type-badge" style="color:{typeColor(node?.type)}">{node?.type}</span>
    <span class="panel-title mono">{shortPath(node?.label || node?.id)}</span>
    <button class="close-btn" on:click={() => dispatch('close')}>✕</button>
  </div>

  <div class="panel-body">
    {#if node}
      <div class="props">
        {#each Object.entries(node) as [k, v]}
          {#if v !== null && v !== undefined && v !== '' && !['id','label','type'].includes(k)}
            <div class="prop-row">
              <span class="prop-key dimmer">{k}</span>
              <span class="prop-val mono">{typeof v === 'object' ? JSON.stringify(v) : v}</span>
            </div>
          {/if}
        {/each}
      </div>

      {#if loading}
        <div class="loading-msg dimmer mono">Loading details...</div>
      {:else if detail?.data}
        <div class="section-title">Details</div>
        <div class="props">
          {#each Object.entries(detail.data) as [k, v]}
            {#if v !== null && v !== undefined}
              <div class="prop-row">
                <span class="prop-key dimmer">{k}</span>
                <span class="prop-val mono">{v}</span>
              </div>
            {/if}
          {/each}
        </div>
      {/if}
    {/if}
  </div>
</div>

<style>
.panel {
  background: var(--bg-1);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  max-height: 40%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-2);
  flex-shrink: 0;
}

.type-badge {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.panel-title {
  font-size: 11px;
  color: var(--text-0);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.close-btn {
  background: none;
  border: none;
  color: var(--text-2);
  font-size: 12px;
  padding: 2px 4px;
  cursor: pointer;
}
.close-btn:hover { color: var(--text-0); background: none; }

.panel-body {
  overflow-y: auto;
  padding: 8px 12px;
  flex: 1;
}

.props { display: flex; flex-direction: column; gap: 3px; }

.prop-row {
  display: flex;
  gap: 8px;
  font-size: 11px;
  line-height: 1.6;
}

.prop-key {
  font-family: var(--font-mono);
  min-width: 90px;
  flex-shrink: 0;
  font-size: 10px;
}

.prop-val {
  font-size: 11px;
  color: var(--text-0);
  word-break: break-all;
}

.section-title {
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-2);
  margin: 10px 0 6px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}

.loading-msg {
  font-size: 11px;
  padding: 8px 0;
}
</style>
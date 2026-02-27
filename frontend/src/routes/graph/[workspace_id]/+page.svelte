<script>
  import { page } from '$app/stores';
  import { onMount, onDestroy } from 'svelte';
  import GraphView from '$lib/GraphView.svelte';
  import NodePanel from '$lib/NodePanel.svelte';
  import ChatPanel from '$lib/ChatPanel.svelte';
  import FilterBar from '$lib/FilterBar.svelte';

  const API = 'http://localhost:8000';

  $: workspaceId = $page.params.workspace_id;
  $: repoUrl = $page.url.searchParams.get('url') || '';

  let graphData = null;
  let loading = true;
  let error = '';
  let selectedNode = null;
  let filters = { types: ['File', 'Function', 'Class'], extensions: [], authors: [] };
  let chatContextNode = null;

  onMount(async () => {
    await loadGraph();
  });

  async function loadGraph() {
    loading = true;
    error = '';
    try {
      const res = await fetch(`${API}/graph/${workspaceId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      graphData = await res.json();
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  function handleNodeSelect(event) {
    selectedNode = event.detail;
    chatContextNode = event.detail;
  }

  function handleNodeDeselect() {
    selectedNode = null;
  }

  function handleClearContext() {
    chatContextNode = null;
  }
</script>

<svelte:head><title>{workspaceId} — Codebase Cartographer</title></svelte:head>

<div class="workspace">
  <!-- Top bar -->
  <header class="topbar">
    <a href="/" class="brand-link">⬡ <span>Codebase Cartographer</span></a>
    <div class="workspace-name mono">{workspaceId}</div>
    <div class="topbar-right">
      {#if graphData}
        <span class="stat dimmer">{graphData.nodes?.length ?? 0} nodes</span>
        <span class="stat dimmer">{graphData.edges?.length ?? 0} edges</span>
      {/if}
      <button on:click={loadGraph} disabled={loading}>
        {loading ? '...' : '↺ Reload'}
      </button>
    </div>
  </header>

  <!-- Filter bar -->
  <FilterBar bind:filters />

  <!-- Main area -->
  <div class="main">
    <!-- Graph panel -->
    <div class="graph-area">
      {#if loading}
        <div class="center-msg">
          <span class="accent mono">Loading graph...</span>
        </div>
      {:else if error}
        <div class="center-msg">
          <span class="err mono">{error}</span>
          <button on:click={loadGraph} style="margin-top:12px">Retry</button>
        </div>
      {:else if graphData}
        <GraphView
          {graphData}
          {filters}
          on:nodeSelect={handleNodeSelect}
          on:nodeDeselect={handleNodeDeselect}
        />
      {/if}
    </div>

    <!-- Right panels -->
    <div class="right-panels">
      {#if selectedNode}
        <NodePanel node={selectedNode} {workspaceId} on:close={handleNodeDeselect} />
      {/if}
      <ChatPanel
        {workspaceId}
        contextNode={chatContextNode}
        on:clearContext={handleClearContext}
      />
    </div>
  </div>
</div>

<style>
.workspace {
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.topbar {
  height: 44px;
  background: var(--bg-1);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 16px;
  gap: 16px;
  flex-shrink: 0;
}

.brand-link {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--accent);
  display: flex;
  align-items: center;
  gap: 6px;
  text-decoration: none;
}
.brand-link span { color: var(--text-1); font-size: 12px; }

.workspace-name {
  font-size: 12px;
  color: var(--text-0);
  padding: 2px 8px;
  background: var(--bg-3);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.topbar-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 12px;
}

.stat { font-family: var(--font-mono); font-size: 11px; }

.main {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.graph-area {
  flex: 1;
  position: relative;
  overflow: hidden;
}

.right-panels {
  width: var(--panel-w);
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--border);
  overflow: hidden;
}

.center-msg {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  font-size: 13px;
}
</style>
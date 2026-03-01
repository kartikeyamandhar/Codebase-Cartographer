<script>
  import { page } from '$app/stores';
  import { onMount, tick } from 'svelte';
  import GraphView from '$lib/GraphView.svelte';
  import NodePanel from '$lib/NodePanel.svelte';
  import ChatPanel from '$lib/ChatPanel.svelte';
  import FilterBar from '$lib/FilterBar.svelte';

  const API = 'http://localhost:8000';
  $: workspaceId = $page.params.workspace_id;

  let graphData = null;
  let loading = true;
  let error = '';
  let selectedNode = null;
  let filters = { types: ['File', 'Function', 'Class', 'Author'] };
  let chatContextNode = null;
  let graphView;

  // Mermaid overlay
  let mermaidDiagram = null;
  let mermaidContainer;

  // Ingestion
  let ingesting = false;
  let ingestStage = '';
  let ingestMessage = '';
  let ingestPercent = 0;
  let ingestError = '';

  onMount(async () => {
    await loadGraph();
    const ingestUrl = new URL(window.location.href).searchParams.get('ingest');
    if (ingestUrl) startIngestion(ingestUrl);
  });

  async function loadGraph() {
    loading = true; error = '';
    try {
      const res = await fetch(`${API}/graph/${workspaceId}`);
      if (!res.ok) throw new Error(`API ${res.status}`);
      graphData = await res.json();
    } catch (e) { error = e.message; }
    finally { loading = false; }
  }

  async function handleMermaid(event) {
    mermaidDiagram = event.detail;
    await tick();  // wait for {#if mermaidDiagram} block + bind:this to resolve
    if (!mermaidContainer) return;
    try {
      const { default: mermaid } = await import('https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs');
      mermaid.initialize({ startOnLoad: false, theme: 'dark' });
      const id = 'md' + Math.random().toString(36).slice(2);
      mermaidContainer.innerHTML = `<pre class="mermaid" id="${id}">${mermaidDiagram}</pre>`;
      await mermaid.run({ nodes: [mermaidContainer.querySelector('.mermaid')] });
    } catch (e) {
      if (mermaidContainer) mermaidContainer.innerHTML = `<pre class="mermaid-raw">${mermaidDiagram}</pre>`;
    }
  }

  function clearDiagram() {
    mermaidDiagram = null;
    if (mermaidContainer) mermaidContainer.innerHTML = '';
  }

  function handleHighlight(event) {
    if (graphView) graphView.highlightNodes(event.detail);
  }

  function handleNodeSelect(e) { selectedNode = e.detail; chatContextNode = e.detail; }
  function handleNodeDeselect() { selectedNode = null; }
  function handleClearContext() { chatContextNode = null; }

  async function startIngestion(githubUrl) {
    ingesting = true; ingestStage = 'cloning'; ingestMessage = 'Starting...'; ingestPercent = 0; ingestError = '';
    try {
      const res = await fetch(`${API}/ingest/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ github_url: githubUrl, workspace_id: workspaceId }),
      });
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        for (const line of decoder.decode(value).split('\n')) {
          if (!line.startsWith('data: ')) continue;
          try {
            const ev = JSON.parse(line.slice(6));
            ingestStage = ev.stage; ingestMessage = ev.message; ingestPercent = ev.percent;
            if (ev.stage === 'ready') { await new Promise(r => setTimeout(r, 600)); ingesting = false; await loadGraph(); return; }
            if (ev.stage === 'error') { ingestError = ev.message; return; }
          } catch {}
        }
      }
    } catch (e) { ingestError = e.message; }
  }
</script>

<svelte:head><title>{workspaceId} — Codebase Cartographer</title></svelte:head>

<div class="workspace">
  <header class="topbar">
    <a href="/" class="brand">⬡ <span>Codebase Cartographer</span></a>
    <div class="ws-badge mono">{workspaceId}</div>
    {#if mermaidDiagram}
      <div class="diagram-badge">Diagram</div>
    {/if}
    <div class="topbar-r">
      {#if mermaidDiagram}
        <button on:click={clearDiagram}>← Back to graph</button>
      {:else}
        {#if graphData}
          <span class="stat">{graphData.nodes?.length ?? 0} nodes</span>
          <span class="stat">{graphData.edges?.length ?? 0} edges</span>
        {/if}
        <button on:click={loadGraph} disabled={loading}>{loading ? '…' : '↺ Reload'}</button>
      {/if}
    </div>
  </header>

  <FilterBar bind:filters />

  <div class="main">
    <div class="graph-area">
      <!-- Mermaid takes over graph area when active -->
      {#if mermaidDiagram}
        <div class="mermaid-stage">
          <div bind:this={mermaidContainer} class="mermaid-inner"></div>
        </div>
      {/if}

      <!-- Graph — kept alive but invisible when diagram showing -->
      <div class:ghost={!!mermaidDiagram}>
        {#if loading}
          <div class="centermsg"><span class="accent mono">Loading…</span></div>
        {:else if error}
          <div class="centermsg">
            <span class="err mono">{error}</span>
            <button on:click={loadGraph} style="margin-top:12px">Retry</button>
          </div>
        {:else if graphData}
          <GraphView
            bind:this={graphView}
            {graphData}
            {filters}
            on:nodeSelect={handleNodeSelect}
            on:nodeDeselect={handleNodeDeselect}
          />
        {/if}
      </div>
    </div>

    <div class="right-panels">
      {#if selectedNode && !mermaidDiagram}
        <NodePanel node={selectedNode} {workspaceId} on:close={handleNodeDeselect} />
      {/if}
      <ChatPanel
        {workspaceId}
        contextNode={chatContextNode}
        on:clearContext={handleClearContext}
        on:highlight={handleHighlight}
        on:mermaid={handleMermaid}
      />
    </div>
  </div>
</div>

{#if ingesting}
  <div class="ingest-veil">
    <div class="ingest-card">
      <div class="ingest-head mono">Ingesting repository</div>
      <div class="ingest-stage accent mono">{ingestStage}</div>
      <div class="ingest-track"><div class="ingest-fill" style="width:{ingestPercent}%"></div></div>
      <div class="ingest-msg dimmer mono">{ingestMessage}</div>
      {#if ingestError}
        <div class="err mono" style="font-size:11px">{ingestError}</div>
        <button on:click={() => ingesting = false} style="margin-top:12px">Dismiss</button>
      {/if}
    </div>
  </div>
{/if}

<style>
.workspace { height:100vh; display:flex; flex-direction:column; overflow:hidden; }

.topbar {
  height:44px; background:var(--bg-1); border-bottom:1px solid var(--border);
  display:flex; align-items:center; padding:0 16px; gap:14px; flex-shrink:0;
}
.brand { font-family:var(--font-mono); font-size:13px; color:var(--accent); display:flex; align-items:center; gap:6px; text-decoration:none; }
.brand span { color:var(--text-1); font-size:12px; }
.ws-badge { font-size:12px; padding:2px 10px; background:var(--bg-3); border:1px solid var(--border); border-radius:var(--radius); }
.diagram-badge { font-family:var(--font-mono); font-size:11px; color:var(--warn); padding:2px 8px; border:1px solid var(--warn); border-radius:var(--radius); }
.topbar-r { margin-left:auto; display:flex; align-items:center; gap:12px; }
.stat { font-family:var(--font-mono); font-size:11px; color:var(--text-2); }

.main { flex:1; display:flex; overflow:hidden; }

.graph-area { flex:1; position:relative; overflow:hidden; }

.graph-area > div:not(.mermaid-stage) {
  position:absolute; inset:0;
}
.ghost { visibility:hidden; pointer-events:none; }

.mermaid-stage {
  position:absolute; inset:0; z-index:10;
  background:var(--bg-0);
  display:flex; align-items:center; justify-content:center;
  overflow:auto; padding:48px;
}
.mermaid-inner { max-width:100%; overflow-x:auto; }
.mermaid-inner :global(svg) { max-width:100%; height:auto; }

:global(.mermaid-raw) {
  font-family:var(--font-mono); font-size:12px; color:var(--text-1);
  white-space:pre-wrap; background:var(--bg-2);
  padding:20px; border-radius:var(--radius); border:1px solid var(--border);
}

.right-panels {
  width:var(--panel-w); flex-shrink:0;
  display:flex; flex-direction:column;
  border-left:1px solid var(--border); overflow:hidden;
}

.centermsg {
  position:absolute; inset:0; display:flex; flex-direction:column;
  align-items:center; justify-content:center; font-size:13px;
}

.ingest-veil {
  position:fixed; inset:0; background:rgba(10,10,17,0.88);
  backdrop-filter:blur(4px); display:flex; align-items:center; justify-content:center; z-index:100;
}
.ingest-card {
  width:420px; background:var(--bg-2); border:1px solid var(--border);
  border-radius:8px; padding:28px 32px; display:flex; flex-direction:column; gap:12px;
}
.ingest-head { font-size:11px; color:var(--text-2); text-transform:uppercase; letter-spacing:0.5px; }
.ingest-stage { font-size:20px; font-weight:500; text-transform:capitalize; }
.ingest-track { height:3px; background:var(--bg-3); border-radius:2px; overflow:hidden; }
.ingest-fill { height:100%; background:var(--accent); transition:width 0.4s ease; }
.ingest-msg { font-size:11px; min-height:16px; }
</style>
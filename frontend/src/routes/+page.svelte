<script>
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  const API = 'http://localhost:8000';

  let workspaces = [];
  let workspacesLoading = true;
  let customUrl = '';
  let customWsId = '';
  let showCustom = false;

  onMount(async () => {
    try {
      const res = await fetch(`${API}/workspaces`);
      if (res.ok) {
        const data = await res.json();
        workspaces = data.workspaces || [];
      }
    } catch(e) {}
    finally { workspacesLoading = false; }
  });

  function openWorkspace(id) {
    goto(`/graph/${id}`);
  }

  function handleKey(e) {
    if (e.key === 'Enter') startIngest();
  }

  function startIngest() {
    if (!customWsId.trim()) return;
    goto(`/graph/${customWsId.trim()}`);
  }
</script>

<svelte:head><title>Codebase Cartographer</title></svelte:head>

<main class="landing">
  <div class="inner">
    <div class="brand">
      <span class="mark">⬡</span>
      <div>
        <h1>Codebase Cartographer</h1>
        <p class="sub">Graph-native codebase intelligence</p>
      </div>
    </div>

    {#if !workspacesLoading && workspaces.length > 0}
      <div class="label">Workspaces</div>
      <div class="ws-list">
        {#each workspaces as ws}
          <button class="ws-row" on:click={() => openWorkspace(ws.workspace_id)}>
            <span class="ws-id">{ws.workspace_id}</span>
            <span class="ws-count">{ws.node_count} nodes</span>
            <span class="ws-arrow">→</span>
          </button>
        {/each}
      </div>
    {:else if workspacesLoading}
      <p class="hint">Connecting...</p>
    {:else}
      <p class="hint">No workspaces found. Ingest a repo first.</p>
    {/if}

    <div class="divider"></div>

    <div class="label">Open workspace by ID</div>
    <div class="row">
      <input
        bind:value={customWsId}
        on:keydown={handleKey}
        placeholder="workspace_id  (e.g. local_dev)"
      />
      <button class="go-btn" on:click={startIngest} disabled={!customWsId.trim()}>Open →</button>
    </div>

    <div class="label" style="margin-top:20px">Ingest a new repo</div>
    <pre class="cmd">python main.py ingest &lt;github_url&gt;</pre>
    <div class="examples">
      {#each ['psf/requests','pallets/flask','httpie/httpie'] as r}
        <code>{r}</code>
      {/each}
    </div>

    <div class="legend">
      {#each [['File','var(--col-file)'],['Function','var(--col-function)'],['Class','var(--col-class)'],['Author','var(--col-author)']] as [t,c]}
        <div class="leg-item"><span class="dot" style="background:{c}"></span>{t}</div>
      {/each}
    </div>
  </div>
</main>

<style>
.landing {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: radial-gradient(ellipse 70% 40% at 50% -5%, rgba(74,222,128,0.05) 0%, transparent 60%), var(--bg-0);
}
.inner { width: 100%; max-width: 480px; padding: 0 20px; }
.brand { display: flex; align-items: center; gap: 14px; margin-bottom: 32px; }
.mark { font-size: 36px; color: var(--accent); filter: drop-shadow(0 0 10px rgba(74,222,128,0.35)); }
h1 { font-family: var(--font-mono); font-size: 20px; font-weight: 500; letter-spacing: -0.3px; }
.sub { font-family: var(--font-mono); font-size: 10px; color: var(--text-2); text-transform: uppercase; letter-spacing: 0.8px; margin-top: 2px; }
.label { font-family: var(--font-mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.6px; color: var(--text-2); margin-bottom: 6px; }
.hint { font-family: var(--font-mono); font-size: 11px; color: var(--text-2); margin-bottom: 16px; }
.ws-list { display: flex; flex-direction: column; gap: 3px; margin-bottom: 20px; }
.ws-row {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 12px; background: var(--bg-2);
  border: 1px solid var(--border); border-radius: var(--radius);
  width: 100%; text-align: left; transition: border-color 0.12s, background 0.12s;
}
.ws-row:hover { border-color: var(--accent); background: var(--accent-dim); }
.ws-id { font-family: var(--font-mono); font-size: 12px; color: var(--accent); flex: 1; }
.ws-count { font-family: var(--font-mono); font-size: 11px; color: var(--text-2); }
.ws-arrow { color: var(--text-2); font-size: 13px; }
.ws-row:hover .ws-arrow { color: var(--accent); }
.divider { border: none; border-top: 1px solid var(--border); margin: 20px 0; }
.row { display: flex; gap: 6px; margin-bottom: 4px; }
.row input { flex: 1; }
.go-btn { white-space: nowrap; padding: 6px 14px; }
.cmd {
  font-family: var(--font-mono); font-size: 11px;
  background: var(--bg-2); border: 1px solid var(--border);
  padding: 8px 12px; border-radius: var(--radius); color: var(--accent);
  margin-bottom: 8px;
}
.examples { display: flex; flex-direction: column; gap: 2px; margin-bottom: 24px; }
.examples code { font-family: var(--font-mono); font-size: 11px; color: var(--text-2); }
.legend { display: flex; gap: 16px; padding-top: 16px; border-top: 1px solid var(--border); }
.leg-item { display: flex; align-items: center; gap: 5px; font-family: var(--font-mono); font-size: 10px; color: var(--text-2); }
.dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
</style>
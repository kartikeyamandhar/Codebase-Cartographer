<script>
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  const API = 'http://localhost:8000';

  let repoUrl = '';
  let submitting = false;
  let error = '';
  let workspaces = [];
  let workspacesLoading = true;

  onMount(async () => {
    try {
      const res = await fetch(`${API}/workspaces`);
      if (res.ok) {
        const data = await res.json();
        workspaces = data.workspaces || [];
      }
    } catch {}
    finally { workspacesLoading = false; }
  });

  function openWorkspace(id) {
    goto(`/graph/${id}`);
  }

  async function handleSubmit() {
    const url = repoUrl.trim();
    if (!url) return;
    error = '';

    // Basic validation
    if (!url.includes('github.com')) {
      error = 'Please enter a valid GitHub URL';
      return;
    }

    // Derive workspace_id from repo name
    const workspaceId = url.replace(/\/$/, '').split('/').pop().toLowerCase().replace(/[^a-z0-9_-]/g, '_');

    // Check if already ingested
    const existing = workspaces.find(w => w.workspace_id === workspaceId);
    if (existing) {
      goto(`/graph/${workspaceId}`);
      return;
    }

    // Navigate to graph page with ?ingest= param — SSE ingestion happens there
    goto(`/graph/${workspaceId}?ingest=${encodeURIComponent(url)}`);
  }

  function handleKey(e) {
    if (e.key === 'Enter') handleSubmit();
  }

  const examples = [
    'https://github.com/psf/requests',
    'https://github.com/pallets/flask',
    'https://github.com/httpie/httpie',
  ];
</script>

<svelte:head><title>Codebase Cartographer</title></svelte:head>

<main class="landing">
  <div class="inner">
    <div class="brand">
      <span class="brand-mark">⬡</span>
      <div>
        <h1>Codebase Cartographer</h1>
        <p class="tagline">Graph-native codebase intelligence</p>
      </div>
    </div>

    <!-- URL input -->
    <div class="ingest-bar">
      <input
        bind:value={repoUrl}
        on:keydown={handleKey}
        placeholder="https://github.com/owner/repo"
        disabled={submitting}
        class="repo-input"
        autofocus
      />
      <button class="go-btn primary" on:click={handleSubmit} disabled={submitting || !repoUrl.trim()}>
        {submitting ? '…' : 'Explore →'}
      </button>
    </div>

    {#if error}
      <div class="input-error mono">{error}</div>
    {/if}

    <div class="examples-row">
      {#each examples as ex}
        <button class="example-chip" on:click={() => { repoUrl = ex; }}>
          {ex.split('/').slice(-2).join('/')}
        </button>
      {/each}
    </div>

    <!-- Existing workspaces -->
    {#if !workspacesLoading && workspaces.length > 0}
      <div class="divider">
        <span class="divider-label mono">or open existing</span>
      </div>
      <div class="workspace-list">
        {#each workspaces as ws}
          <button class="ws-card" on:click={() => openWorkspace(ws.workspace_id)}>
            <span class="ws-id mono accent">{ws.workspace_id}</span>
            <span class="ws-meta dimmer mono">{ws.node_count} nodes</span>
            <span class="ws-arrow dimmer">→</span>
          </button>
        {/each}
      </div>
    {/if}

    <div class="legend">
      <div class="leg-item"><span class="lsq" style="background:#60a5fa"></span>File</div>
      <div class="leg-item"><span class="ldi" style="background:#5eead4"></span>Function</div>
      <div class="leg-item"><span class="lhx" style="background:#c084fc"></span>Class</div>
    </div>
  </div>
</main>

<style>
.landing {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    radial-gradient(ellipse 80% 50% at 50% -10%, rgba(94,234,212,0.06) 0%, transparent 60%),
    var(--bg-0);
}

.inner {
  width: 100%;
  max-width: 540px;
  padding: 0 24px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 40px;
}

.brand-mark {
  font-size: 42px;
  color: var(--accent);
  line-height: 1;
  filter: drop-shadow(0 0 14px rgba(94,234,212,0.35));
}

h1 {
  font-family: var(--font-mono);
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.5px;
  color: var(--text-0);
}

.tagline {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-2);
  margin-top: 3px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

.ingest-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.repo-input {
  flex: 1;
  font-size: 13px;
  height: 42px;
  padding: 0 14px;
}

.go-btn {
  height: 42px;
  padding: 0 20px;
  font-size: 13px;
  white-space: nowrap;
  flex-shrink: 0;
}

.input-error {
  font-size: 11px;
  color: var(--err);
  margin-bottom: 8px;
}

.examples-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 32px;
}

.example-chip {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-2);
  background: var(--bg-2);
  border: 1px solid var(--border);
  padding: 3px 10px;
  border-radius: 20px;
  cursor: pointer;
  transition: color 0.1s, border-color 0.1s;
}
.example-chip:hover { color: var(--accent); border-color: var(--accent); background: var(--bg-2); }

.divider {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.divider::before, .divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border);
}
.divider-label {
  font-size: 10px;
  color: var(--text-2);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  white-space: nowrap;
}

.workspace-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 32px;
}

.ws-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  text-align: left;
  width: 100%;
  transition: border-color 0.12s, background 0.12s;
}
.ws-card:hover { border-color: var(--accent); background: var(--accent-dim); }
.ws-card:hover .ws-arrow { color: var(--accent); }

.ws-id { font-size: 13px; flex: 1; }
.ws-meta { font-size: 11px; }
.ws-arrow { font-size: 14px; margin-left: auto; }

.legend {
  display: flex;
  gap: 20px;
  padding-top: 24px;
  border-top: 1px solid var(--border);
  margin-top: 8px;
}
.leg-item {
  display: flex;
  align-items: center;
  gap: 7px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-2);
}
.lsq { display:inline-block; width:14px; height:9px; border-radius:2px; }
.ldi { display:inline-block; width:10px; height:10px; transform:rotate(45deg); }
.lhx { display:inline-block; width:12px; height:12px; border-radius:2px; }
</style>
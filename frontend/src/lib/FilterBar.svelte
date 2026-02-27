<script>
  export let filters = { types: ['File', 'Function', 'Class'], extensions: [], authors: [] };

  const ALL_TYPES = ['File', 'Function', 'Class', 'Author'];

  function toggleType(t) {
    if (filters.types.includes(t)) {
      filters.types = filters.types.filter(x => x !== t);
    } else {
      filters.types = [...filters.types, t];
    }
    filters = { ...filters };
  }

  const TYPE_COLORS = {
    File: 'var(--col-file)',
    Function: 'var(--col-function)',
    Class: 'var(--col-class)',
    Author: 'var(--col-author)',
  };
</script>

<div class="filterbar">
  <span class="label dimmer mono">Show:</span>
  {#each ALL_TYPES as t}
    <button
      class="type-btn"
      class:active={filters.types.includes(t)}
      style="--type-color:{TYPE_COLORS[t]}"
      on:click={() => toggleType(t)}
    >
      <span class="dot"></span>{t}
    </button>
  {/each}
</div>

<style>
.filterbar {
  height: 32px;
  background: var(--bg-1);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 12px;
  gap: 6px;
  flex-shrink: 0;
}

.label { font-size: 10px; margin-right: 2px; }

.type-btn {
  font-size: 10px;
  padding: 2px 8px;
  display: flex;
  align-items: center;
  gap: 5px;
  opacity: 0.4;
  border-color: transparent;
  background: transparent;
  color: var(--text-1);
  transition: opacity 0.15s;
}
.type-btn.active {
  opacity: 1;
  border-color: var(--type-color);
  color: var(--type-color);
  background: color-mix(in srgb, var(--type-color) 10%, transparent);
}
.type-btn:hover { opacity: 0.8; }

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--type-color);
  flex-shrink: 0;
}
</style>
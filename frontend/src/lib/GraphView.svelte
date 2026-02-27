<script>
  import { onMount, onDestroy, createEventDispatcher } from 'svelte';
  import { browser } from '$app/environment';

  export let graphData = null;
  export let filters = {};

  const dispatch = createEventDispatcher();

  let container;
  let cy;

  const TYPE_COLORS = {
    File:     '#60a5fa',
    Function: '#4ade80',
    Class:    '#a78bfa',
    Author:   '#fb923c',
  };

  const DOMAIN_COLORS = {
    auth:     '#f87171',
    payments: '#fb923c',
    database: '#a78bfa',
    api:      '#60a5fa',
    config:   '#94a3b8',
    utils:    '#6ee7b7',
    testing:  '#fbbf24',
    infra:    '#f472b6',
    ui:       '#34d399',
    logging:  '#c084fc',
  };

  onMount(async () => {
    if (!browser) return;
    const cytoscape = (await import('cytoscape')).default;
    if (graphData) init(cytoscape);
  });

  onDestroy(() => cy?.destroy());

  $: if (cy && graphData) updateGraph();
  $: if (cy && filters) applyFilters();

  function nodeColor(ele) {
    const domain = ele.data('domain_tag');
    if (domain && DOMAIN_COLORS[domain]) return DOMAIN_COLORS[domain];
    return TYPE_COLORS[ele.data('type')] || '#555';
  }

  function nodeSize(degree) {
    const d = Math.max(degree || 1, 1);
    return Math.max(12, Math.min(48, 10 + Math.log(d + 1) * 8));
  }

  function buildElements(data) {
    if (!data) return [];
    return [
      ...(data.nodes || []).map(n => ({ data: { ...n.data } })),
      ...(data.edges || []).map(e => ({ data: { ...e.data } })),
    ];
  }

  function init(cytoscape) {
    cy = cytoscape({
      container,
      elements: buildElements(graphData),
      style: styles(),
      layout: {
        name: 'cose',
        animate: false,
        randomize: false,
        idealEdgeLength: 60,
        nodeRepulsion: 6000,
        gravity: 0.4,
        numIter: 500,
      },
      minZoom: 0.05,
      maxZoom: 5,
      wheelSensitivity: 0.3,
    });

    cy.on('tap', 'node', e => {
      dispatch('nodeSelect', { ...e.target.data() });
    });
    cy.on('tap', e => {
      if (e.target === cy) dispatch('nodeDeselect');
    });
  }

  function updateGraph() {
    if (!cy || !graphData) return;
    cy.elements().remove();
    cy.add(buildElements(graphData));
    cy.style(styles());
    cy.layout({ name: 'cose', animate: false, randomize: false, idealEdgeLength: 60, nodeRepulsion: 6000 }).run();
  }

  function applyFilters() {
    if (!cy) return;
    const show = new Set(filters.types || ['File','Function','Class','Author']);
    cy.nodes().forEach(n => n.style('display', show.has(n.data('type')) ? 'element' : 'none'));
    cy.edges().forEach(e => {
      const s = cy.getElementById(e.data('source'));
      const t = cy.getElementById(e.data('target'));
      e.style('display', s.style('display') !== 'none' && t.style('display') !== 'none' ? 'element' : 'none');
    });
  }

  function styles() {
    return [
      {
        selector: 'node',
        style: {
          'background-color': nodeColor,
          'width': ele => nodeSize(ele.data('degree')),
          'height': ele => nodeSize(ele.data('degree')),
          'label': 'data(label)',
          'font-family': 'IBM Plex Mono',
          'font-size': '8px',
          'color': '#6a6a80',
          'text-valign': 'bottom',
          'text-halign': 'center',
          'text-margin-y': '3px',
          'text-max-width': '80px',
          'text-wrap': 'ellipsis',
          'border-width': 0,
          'transition-property': 'border-width, border-color',
          'transition-duration': '0.1s',
        }
      },
      {
        selector: 'node:selected',
        style: { 'border-width': 2, 'border-color': '#4ade80' }
      },
      {
        selector: 'node.highlighted',
        style: { 'border-width': 2, 'border-color': '#fb923c' }
      },
      {
        selector: 'edge',
        style: {
          'line-color': ele => ({ IMPORTS:'#1e3a5f', CALLS:'#1a3a2a', OWNS:'#3a2a1a' }[ele.data('type')] || '#222'),
          'target-arrow-color': ele => ({ IMPORTS:'#1e3a5f', CALLS:'#1a3a2a', OWNS:'#3a2a1a' }[ele.data('type')] || '#222'),
          'target-arrow-shape': 'triangle',
          'arrow-scale': 0.6,
          'width': 1,
          'curve-style': 'bezier',
          'line-style': ele => ele.data('resolved') === false ? 'dashed' : 'solid',
          'opacity': 0.5,
        }
      },
    ];
  }

  export function highlightNodes(ids) {
    if (!cy) return;
    cy.nodes().removeClass('highlighted');
    ids.forEach(id => cy.getElementById(id).addClass('highlighted'));
    const hl = cy.nodes('.highlighted');
    if (hl.length) cy.animate({ fit: { eles: hl, padding: 80 }, duration: 350 });
  }
</script>

<div bind:this={container} class="cy"></div>

<style>
.cy {
  width: 100%;
  height: 100%;
  background: var(--bg-0);
  cursor: grab;
}
.cy:active { cursor: grabbing; }
</style>
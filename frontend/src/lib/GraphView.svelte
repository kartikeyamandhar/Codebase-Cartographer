<script>
  import { onMount, onDestroy, createEventDispatcher } from 'svelte';
  import { browser } from '$app/environment';

  export let graphData = null;
  export let filters = {};

  const dispatch = createEventDispatcher();

  let container;
  let cy;

  const DOMAIN_COLORS = {
    auth:     '#f87171',
    payments: '#fb923c',
    database: '#a78bfa',
    api:      '#60a5fa',
    config:   '#94a3b8',
    utils:    '#5eead4',
    testing:  '#fbbf24',
    infra:    '#f472b6',
    ui:       '#34d399',
    logging:  '#c084fc',
  };
  const TYPE_COLORS = {
    File:     '#60a5fa',
    Function: '#5eead4',
    Class:    '#c084fc',
    Author:   '#fb923c',
  };

  function getColor(type, domain) {
    if (domain && DOMAIN_COLORS[domain]) return DOMAIN_COLORS[domain];
    return TYPE_COLORS[type] || '#60a5fa';
  }

  function getShape(type) {
    if (type === 'File') return 'round-rectangle';
    if (type === 'Function') return 'diamond';
    if (type === 'Class') return 'hexagon';
    return 'ellipse';
  }

  function getEdgeLabel(type, resolved) {
    if (type === 'IMPORTS') return 'imports';
    if (type === 'CALLS') return resolved === false ? 'calls (indirect)' : 'calls';
    if (type === 'OWNS') return 'owns';
    return (type || '').toLowerCase();
  }

  function getNodeWidth(type, degree) {
    if (type === 'File') return Math.max(130, Math.min(190, 130 + (degree || 1) * 3));
    return 110;
  }

  onMount(async () => {
    if (!browser) return;
    const cytoscape = (await import('cytoscape')).default;
    if (graphData) init(cytoscape);
  });

  onDestroy(() => cy?.destroy());

  $: if (cy && graphData) update();
  $: if (cy && filters) applyFilters();

  function buildElements(data) {
    if (!data) return [];

    let nodes = (data.nodes || []).slice(0, 25);
    const allEdges = data.edges || [];
    const nodeIds = new Set(nodes.map(n => n.data.id));

    const edges = allEdges
      .filter(e =>
        nodeIds.has(e.data.source) &&
        nodeIds.has(e.data.target) &&
        e.data.source !== e.data.target
      )
      .slice(0, 300);

    // Drop orphans — nodes with no edges (except top 5)
    const connected = new Set();
    edges.forEach(e => { connected.add(e.data.source); connected.add(e.data.target); });
    nodes.slice(0, 5).forEach(n => connected.add(n.data.id));
    nodes = nodes.filter(n => connected.has(n.data.id));

    const cyNodes = nodes.map(n => ({
      data: {
        id: n.data.id,
        shortLabel: n.data.label || n.data.id,
        type: n.data.type || 'File',
        domain_tag: n.data.domain_tag || '',
        semantic_role: n.data.semantic_role || '',
        degree: n.data.degree || 1,
        color: getColor(n.data.type, n.data.domain_tag),
        shape: getShape(n.data.type),
        nw: getNodeWidth(n.data.type, n.data.degree),
      }
    }));

    const cyEdges = edges.map((e, i) => ({
      data: {
        id: `e${i}`,
        source: e.data.source,
        target: e.data.target,
        type: e.data.type,
        resolved: e.data.resolved,
        elabel: getEdgeLabel(e.data.type, e.data.resolved),
      }
    }));

    return [...cyNodes, ...cyEdges];
  }

  function init(cytoscape) {
    cy = cytoscape({
      container,
      elements: buildElements(graphData),
      style: styles(),
      layout: layout(),
      minZoom: 0.06,
      maxZoom: 4,
      wheelSensitivity: 0.2,
    });

    cy.on('tap', 'node', e => {
      cy.nodes().removeClass('selected');
      e.target.addClass('selected');
      dispatch('nodeSelect', { ...e.target.data() });
    });
    cy.on('tap', e => {
      if (e.target === cy) {
        cy.nodes().removeClass('selected');
        dispatch('nodeDeselect');
      }
    });
    cy.ready(() => {
      dispatch('counts', { nodes: cy.nodes().length, edges: cy.edges().length });
    });
  }

  function layout() {
    return {
      name: 'cose',
      animate: true,
      animationDuration: 600,
      randomize: false,
      idealEdgeLength: 130,
      nodeRepulsion: 18000,
      gravity: 0.35,
      numIter: 1000,
      fit: true,
      padding: 60,
      nodeDimensionsIncludeLabels: true,
    };
  }

  function update() {
    if (!cy) return;
    cy.elements().remove();
    cy.add(buildElements(graphData));
    cy.style(styles());
    cy.layout(layout()).run();
  }

  function applyFilters() {
    if (!cy) return;
    const show = new Set(filters.types || ['File', 'Function', 'Class', 'Author']);
    cy.nodes().forEach(n => n.style('display', show.has(n.data('type')) ? 'element' : 'none'));
    cy.edges().forEach(e => {
      const s = cy.getElementById(e.data('source'));
      const t = cy.getElementById(e.data('target'));
      e.style('display', s.style('display') !== 'none' && t.style('display') !== 'none' ? 'element' : 'none');
    });
  }

  export function highlightNodes(ids) {
    if (!cy) return;
    const idSet = new Set(ids);
    cy.nodes().forEach(n => {
      n.removeClass('highlighted dimmed');
      if (ids.length > 0) {
        idSet.has(n.data('id')) ? n.addClass('highlighted') : n.addClass('dimmed');
      }
    });
    const hl = cy.nodes('.highlighted');
    if (hl.length) cy.animate({ fit: { eles: hl, padding: 120 }, duration: 400 });
    setTimeout(() => { if (cy) cy.nodes().removeClass('highlighted dimmed'); }, 5000);
  }

  function styles() {
    return [
      {
        selector: 'node',
        style: {
          'shape': 'data(shape)',
          'width': 'data(nw)',
          'height': 44,
          'background-color': 'data(color)',
          'background-opacity': 0.82,
          'border-width': 1.5,
          'border-color': 'data(color)',
          'border-opacity': 0.5,
          'label': 'data(shortLabel)',
          'font-family': 'IBM Plex Mono, monospace',
          'font-size': '11px',
          'font-weight': '500',
          'color': '#f0f0f8',
          'text-valign': 'center',
          'text-halign': 'center',
          'text-max-width': '120px',
          'text-wrap': 'ellipsis',
          'min-zoomed-font-size': 7,
          'transition-property': 'border-width, border-color, background-opacity',
          'transition-duration': '0.15s',
        }
      },
      {
        selector: 'node[type = "File"]',
        style: { 'font-weight': '600', 'font-size': '12px', 'height': 48 }
      },
      {
        selector: 'node[type = "Function"]',
        style: { 'font-size': '10px', 'font-weight': '400', 'height': 48, 'width': 110 }
      },
      {
        selector: 'node.selected',
        style: { 'border-width': 3, 'border-color': '#ffffff', 'border-opacity': 1, 'background-opacity': 1, 'z-index': 10 }
      },
      {
        selector: 'node.highlighted',
        style: { 'border-width': 3, 'border-color': '#fbbf24', 'border-opacity': 1, 'background-opacity': 1, 'z-index': 10 }
      },
      {
        selector: 'node.dimmed',
        style: { 'background-opacity': 0.12, 'border-opacity': 0.08, 'color': '#50507a' }
      },
      {
        selector: 'edge',
        style: {
          'width': 1.5,
          'line-color': '#252540',
          'target-arrow-color': '#353568',
          'target-arrow-shape': 'triangle',
          'arrow-scale': 0.75,
          'curve-style': 'bezier',
          'opacity': 0.75,
          'label': 'data(elabel)',
          'font-family': 'IBM Plex Mono, monospace',
          'font-size': '9px',
          'color': '#5858a0',
          'text-rotation': 'autorotate',
          'text-margin-y': -7,
          'text-background-color': '#13131a',
          'text-background-opacity': 0.75,
          'text-background-padding': '2px',
          'min-zoomed-font-size': 8,
        }
      },
      { selector: 'edge[type = "IMPORTS"]', style: { 'line-color': '#1e3a6e', 'target-arrow-color': '#2a4e94' } },
      { selector: 'edge[type = "CALLS"]',   style: { 'line-color': '#1a4038', 'target-arrow-color': '#2a6050' } },
      { selector: 'edge[type = "OWNS"]',    style: { 'line-color': '#3a2a10', 'target-arrow-color': '#604020' } },
      { selector: 'edge[resolved = false]', style: { 'line-style': 'dashed', 'opacity': 0.35 } },
      { selector: 'edge.highlighted',       style: { 'line-color': '#fbbf24', 'target-arrow-color': '#fbbf24', 'opacity': 1, 'width': 2.5 } },
    ];
  }
</script>

<div bind:this={container} class="cy">
  <div class="legend">
    <div class="leg-item"><span class="ls rect"></span>File</div>
    <div class="leg-item"><span class="ls diamond"></span>Function</div>
    <div class="leg-item"><span class="ls hex"></span>Class</div>
    <div class="leg-sep"></div>
    <div class="leg-item"><span class="leg-edge imports"></span>imports</div>
    <div class="leg-item"><span class="leg-edge calls"></span>calls</div>
  </div>
</div>

<style>
.cy {
  width: 100%;
  height: 100%;
  background: radial-gradient(ellipse 75% 65% at 50% 45%, #1c1c2e 0%, #13131a 100%);
  position: relative;
  cursor: grab;
}
.cy:active { cursor: grabbing; }

.legend {
  position: absolute;
  bottom: 14px;
  left: 14px;
  display: flex;
  align-items: center;
  gap: 12px;
  background: rgba(19,19,26,0.85);
  border: 1px solid #2a2a44;
  padding: 6px 14px;
  border-radius: 6px;
  z-index: 10;
  pointer-events: none;
  backdrop-filter: blur(4px);
}

.leg-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  color: #8888b0;
}

.leg-sep { width: 1px; height: 12px; background: #2a2a44; }

.ls {
  display: inline-block;
  width: 14px;
  height: 10px;
}
.rect   { background: #60a5fa; border-radius: 2px; }
.diamond { background: #5eead4; transform: rotate(45deg); width: 10px; height: 10px; }
.hex    { background: #c084fc; border-radius: 2px; }

.leg-edge {
  display: inline-block;
  width: 22px;
  height: 2px;
  position: relative;
}
.imports { background: #2a4e94; }
.calls   { background: #2a6050; }
</style>
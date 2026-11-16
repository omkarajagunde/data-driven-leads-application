<script>
  import { onDestroy, onMount } from 'svelte';
  import { api } from './api.js';
  import { num } from './format.js';
  import InsightCard from './InsightCard.svelte';

  // Four levels; the zoom decides which one is showing, and each answers its own question.
  const LEVELS = [
    { id: 'region', name: 'City pulse', line: 'How big each market is and which way prices are moving.', unlocks: ['Price per sq ft', 'QoQ and YoY change', 'Launches'] },
    { id: 'zone', name: 'Hot zones', line: 'Which part of the city is heating up, and where builders are launching.', unlocks: ['Zone against zone', 'Launch hotspots'] },
    { id: 'pincode', name: 'Pincode heat', line: 'Each pincode is raised by the flats on offer. Colour is the metric you pick.', unlocks: ['Size mix', 'Unsold stock', 'Top builders'] },
    { id: 'project', name: 'Projects', line: 'Every registered project: schedule, progress, complaints, court cases.', unlocks: ['On time or late', 'Construction progress', 'Court cases'] },
  ];
  const BREAKS = [8, 10.6, 13.4]; // zoom where each next level starts
  const levelOf = (z) => (z < BREAKS[0] ? 0 : z < BREAKS[1] ? 1 : z < BREAKS[2] ? 2 : 3);
  const METRICS = [
    { id: 'price', name: 'Price', hint: 'Price per sq ft' },
    { id: 'momentum', name: 'Momentum', hint: 'Price change, last quarter' },
    { id: 'supply', name: 'Supply', hint: 'Unsold flats' },
  ];
  const RAMP = ['#2a1d5c', '#5b2a8c', '#a3367f', '#e0575a', '#f99a3e', '#fde05a'];
  const ZONE_COLOUR = { central: '#f5b301', east: '#5fd38a', west: '#f06fb4', north: '#59c8f2', south: '#ff7a59' };
  const SCHEDULE_COLOUR = { on_time: '#3ddc97', early: '#3ddc97', completed: '#6aa8ff', late: '#ff5b5b', overdue: '#ff5b5b' };
  const STYLE = 'https://tiles.openfreemap.org/styles/dark';
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const PLURAL = { region: 'regions', zone: 'zones', pincode: 'pincodes', project: 'projects' };

  let section = $state();
  let stageEl = $state();
  let mapEl = $state();
  let progress = $state(0);
  let stage = $state(0);
  let zoom = $state(5);
  let free = $state(false);
  let ready = $state(false);
  let failed = $state('');
  let metric = $state('price');
  let currency = $state('inr');
  let data = $state.raw(null); // large and read-only; deep reactivity would only cost time
  let selected = $state(null); // the docked card: nearest thing to the middle, or what was tapped
  let narrow = $state(false); // phone layout: the card is a bottom sheet that starts small
  let expanded = $state(false);
  let sheetFor = null;
  $effect(() => { const id = selected?.data?.id; if (id !== sheetFor) { sheetFor = id; expanded = false; } });
  let hovered = $state(null); // the floating card beside the pointer
  let pointer = $state(null);
  let cardH = $state(0);
  let scale = $state({ lo: '', hi: '' });

  const level = $derived(ready ? levelOf(zoom) : 0);
  const fill = (i) => (free ? (i <= level ? 1 : 0) : clamp(progress * 4 - i, 0, 1));

  let maplibre, map, views = [], ticking = false, orbit = 0, picked = false, canHover = false;
  const byId = new Map();
  let hoverKey = null;

  onMount(() => {
    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => { ticking = false; track(); });
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    return () => { window.removeEventListener('scroll', onScroll); window.removeEventListener('resize', onScroll); };
  });
  onDestroy(() => { cancelAnimationFrame(orbit); map?.remove(); });

  $effect(() => { if (mapEl && !map) start(); });
  $effect(() => { metric; currency; if (ready) paint(); });

  function track() {
    if (!section) return;
    const box = section.getBoundingClientRect();
    const run = box.height - window.innerHeight;
    progress = run > 0 ? clamp(-box.top / run, 0, 1) : 0;
    const next = Math.min(3, Math.floor(progress * 4));
    if (next !== stage) {
      stage = next;
      if (!free) go(next);
    }
  }

  // ---------------------------------------------------------------- shapes
  function hull(points) {
    const p = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    if (p.length < 3) return null;
    const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const half = (list) => {
      const out = [];
      for (const q of list) {
        while (out.length >= 2 && cross(out[out.length - 2], out[out.length - 1], q) <= 0) out.pop();
        out.push(q);
      }
      out.pop();
      return out;
    };
    return [...half(p), ...half([...p].reverse())];
  }

  // A zone's shape: the hull of its pincodes pushed outwards a little so it reads as an area, not a wire.
  function zoneShape(pts) {
    const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length, cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
    const h = hull(pts);
    const grow = (p) => { const dx = p[0] - cx, dy = p[1] - cy, len = Math.hypot(dx, dy) || 1; return [p[0] + (dx / len) * 0.012, p[1] + (dy / len) * 0.012]; };
    if (h && h.length >= 3) { const ring = h.map(grow); return [[...ring, ring[0]]]; }
    return [circle(cx, cy, 1800, 24)];
  }

  function circle(lng, lat, metres, sides) {
    const out = [];
    const dLat = metres / 111320, dLng = metres / (111320 * Math.cos((lat * Math.PI) / 180));
    for (let i = 0; i <= sides; i++) {
      const a = (i / sides) * Math.PI * 2 + Math.PI / 6;
      out.push([lng + Math.cos(a) * dLng, lat + Math.sin(a) * dLat]);
    }
    return out;
  }

  // ---------------------------------------------------------------- data to features
  const short = (inr, usd) => {
    if (currency === 'usd') return usd == null ? '' : `$${Math.round(usd).toLocaleString('en-US')}`;
    if (inr == null) return '';
    return inr >= 1e5 ? `₹${(inr / 1e5).toFixed(1)}L` : inr >= 1e3 ? `₹${(inr / 1e3).toFixed(1)}k` : `₹${Math.round(inr)}`;
  };
  const priceOf = (d) => (d.price_per_sqft ? short(d.price_per_sqft.inr, d.price_per_sqft.usd) : '');
  const changeOf = (d) => { const v = d.trend?.price_qoq_pct; return v == null ? '' : `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(1)}%`; };
  const regionName = (id) => data?.regions.find((r) => r.id === id)?.name ?? id;
  const fc = (list) => ({ type: 'FeatureCollection', features: list });

  function metricValue(d) {
    if (metric === 'price') return d.price_per_sqft?.inr ?? null;
    if (metric === 'momentum') return d.trend?.price_qoq_pct ?? null;
    return d.units_unsold || null;
  }

  // Rank-based 0..1 so Mumbai's prices do not wash every Pune pincode into one colour.
  function ranks(rows) {
    const vals = rows.map(metricValue).filter((v) => v != null).sort((a, b) => a - b);
    const at = (v) => (v == null || vals.length < 2 ? -1 : vals.findIndex((x) => x >= v) / (vals.length - 1));
    const fmt = (v) => (metric === 'price' ? short(v, v / 88) : metric === 'momentum' ? `${v.toFixed(1)}%` : num(v));
    return { at, lo: vals.length ? fmt(vals[0]) : '', hi: vals.length ? fmt(vals[vals.length - 1]) : '' };
  }

  function features(kind) {
    const rows = data[PLURAL[kind]];
    const r = kind === 'project' ? null : ranks(rows.filter((d) => d.projects));
    if (kind === 'pincode') scale = { lo: r.lo, hi: r.hi };
    return rows.map((d) => {
      const props = { id: d.id, kind };
      let geometry = { type: 'Point', coordinates: [d.longitude, d.latitude] };
      if (kind === 'project') {
        Object.assign(props, {
          l1: (d.name ?? '').length > 26 ? `${d.name.slice(0, 25)}…` : d.name,
          l2: priceOf(d) ? `${priceOf(d)}/sqft` : d.units_total ? `${num(d.units_total)} flats` : '',
          l3: '', up: 1,
          colour: SCHEDULE_COLOUR[d.schedule] ?? '#9aa3b5', units: d.units_total ?? 0,
        });
      } else {
        Object.assign(props, {
          t: d.projects ? r.at(metricValue(d)) : -1, projects: d.projects, units: d.units_total,
          l1: kind === 'region' ? d.name : kind === 'zone' ? `${regionName(d.region_id)} · ${d.name}` : `${d.id}${d.area ? ` ${d.area}` : ''}`,
          l2: d.projects ? [priceOf(d), kind === 'region' ? `· ${num(d.projects)} projects` : ''].filter(Boolean).join(' ') : 'Coming soon',
          l3: d.projects ? changeOf(d) : '', up: (d.trend?.price_qoq_pct ?? 0) >= 0 ? 1 : 0,
          zone: ZONE_COLOUR[d.zone_id] ?? '#f5b301',
        });
        if (kind === 'region') {
          // the nearest other region decides which side this pill takes on a phone
          const near = rows.filter((o) => o !== d).sort((a, b) => ((a.latitude - d.latitude) ** 2 + (a.longitude - d.longitude) ** 2) - ((b.latitude - d.latitude) ** 2 + (b.longitude - d.longitude) ** 2))[0];
          props.anchor = !near || d.projects >= near.projects ? 'top' : 'bottom';
        }
        if (kind === 'zone' && d.boundary) geometry = d.boundary;
        else if (kind === 'zone') {
          const pts = data.pincodes.filter((p) => p.region_id === d.region_id && p.zone_id === d.zone_id).map((p) => [p.longitude, p.latitude]);
          geometry = { type: 'Polygon', coordinates: zoneShape(pts) };
        }
      }
      return { type: 'Feature', properties: props, geometry };
    });
  }

  const zoneCentres = () => fc(features('zone').map((f, i) => ({ ...f, geometry: { type: 'Point', coordinates: [data.zones[i].longitude, data.zones[i].latitude] } })));
  // Each pincode is raised from its real postal outline when one is loaded, otherwise from a small hexagon.
  // Outlines cover far more ground than a hexagon, so they rise less for the same number of flats.
  const columns = () => fc(features('pincode').filter((f) => f.properties.projects).map((f) => {
    const outline = byId.get(`pincode:${f.properties.id}`)?.boundary;
    const units = f.properties.units ?? 0;
    return {
      ...f,
      properties: { ...f.properties, h: outline ? 60 + 14 * Math.sqrt(units) : 120 + 38 * Math.sqrt(units) },
      geometry: outline ?? { type: 'Polygon', coordinates: [circle(...f.geometry.coordinates, 520, 6)] },
    };
  }));
  // Every loaded outline, for the thin borders (pincodes without projects included).
  const outlines = () => fc((data?.pincodes ?? []).filter((p) => p.boundary).map((p) => ({
    type: 'Feature', properties: { id: p.id, zone: ZONE_COLOUR[p.zone_id] ?? '#f5b301', projects: p.projects }, geometry: p.boundary,
  })));
  const rampExpr = (fallback) => ['case', ['<', ['get', 't'], 0], fallback,
    ['interpolate', ['linear'], ['get', 't'], ...RAMP.flatMap((c, i) => [i / (RAMP.length - 1), c])]];

  // ---------------------------------------------------------------- map
  function pillImage() {
    const s = 2, w = 40 * s, h = 28 * s, r = 9 * s;
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d');
    g.fillStyle = 'rgba(10,12,20,0.92)';
    g.strokeStyle = 'rgba(255,255,255,0.18)';
    g.lineWidth = s;
    g.beginPath(); g.roundRect(s / 2, s / 2, w - s, h - s, r); g.fill(); g.stroke();
    return { img: g.getImageData(0, 0, w, h), opts: { pixelRatio: s, stretchX: [[r, w - r]], stretchY: [[r, h - r]], content: [r, r * 0.6, w - r, h - r * 0.6] } };
  }

  async function start() {
    maplibre = await import('maplibre-gl');
    // Bundled, the worker no longer sits next to the library, so say where Vite put it.
    maplibre.setWorkerUrl((await import('maplibre-gl/dist/maplibre-gl-worker.mjs?url')).default);
    canHover = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
    const small = window.matchMedia('(max-width: 60rem)');
    narrow = small.matches;
    small.addEventListener('change', (e) => (narrow = e.matches));
    map = new maplibre.Map({ container: mapEl, style: STYLE, center: [75.2, 16.8], zoom: 5.2, maxPitch: 70, attributionControl: { compact: true } });
    lock(true);
    map.addControl(new maplibre.NavigationControl({ visualizePitch: true }), 'bottom-left');
    try {
      [data] = await Promise.all([api('/v1/map/insights'), new Promise((r) => map.once('load', r))]);
    } catch (e) {
      failed = 'The map could not load its figures. Is the API running?';
      return;
    }
    data.projects = []; // filled per view by loadProjects(), only once the map is zoomed in that far
    for (const kind of Object.keys(PLURAL)) for (const d of data[PLURAL[kind]]) byId.set(`${kind}:${d.id}`, d);
    tune();
    layers();
    views = plan();
    map.on('move', () => (zoom = map.getZoom()));
    map.on('moveend', settle);
    map.on('moveend', () => { if (!orbit) loadProjects(); });
    map.on('dragstart', stopOrbit);
    ready = true;
    track();
    go(stage, false);
  }

  // Quieter basemap so the data glows: night ground, dimmer labels, 3D buildings at street level.
  function tune() {
    for (const l of map.getStyle().layers) {
      if (l.type === 'background') map.setPaintProperty(l.id, 'background-color', '#070910');
      if (l.type === 'symbol' && l.layout?.['text-field']) map.setPaintProperty(l.id, 'text-opacity', 0.5);
      if (l.type === 'fill' && l['source-layer'] === 'water') map.setPaintProperty(l.id, 'fill-color', '#0a1424');
    }
    const firstLabel = map.getStyle().layers.find((l) => l.type === 'symbol')?.id;
    map.addLayer({
      id: 'buildings-3d', type: 'fill-extrusion', source: 'openmaptiles', 'source-layer': 'building', minzoom: 14,
      paint: {
        'fill-extrusion-color': '#1b2236',
        'fill-extrusion-height': ['coalesce', ['get', 'render_height'], 8],
        'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
        'fill-extrusion-opacity': ['interpolate', ['linear'], ['zoom'], 14, 0, 15, 0.8],
      },
    }, firstLabel);
    const { img, opts } = pillImage();
    map.addImage('pill', img, opts);
  }

  function layers() {
    map.addSource('regions', { type: 'geojson', data: fc(features('region')), promoteId: 'id' });
    map.addSource('zones', { type: 'geojson', data: fc(features('zone')), promoteId: 'id' });
    map.addSource('zone-centres', { type: 'geojson', data: zoneCentres(), promoteId: 'id' });
    map.addSource('pins', { type: 'geojson', data: fc(features('pincode')), promoteId: 'id' });
    map.addSource('columns', { type: 'geojson', data: columns(), promoteId: 'id' });
    map.addSource('outlines', { type: 'geojson', data: outlines(), promoteId: 'id' });
    map.addSource('projects', { type: 'geojson', data: fc(features('project')), promoteId: 'id' });

    const fade = (a, b, max = 1) => (a > 0
      ? ['interpolate', ['linear'], ['zoom'], a - 0.4, 0, a, max, b, max, b + 0.4, 0]
      : ['interpolate', ['linear'], ['zoom'], b, max, b + 0.4, 0]);
    const lit = (on, off) => ['case', ['boolean', ['feature-state', 'hover'], false], on, off];

    // regions: glowing bubbles
    map.addLayer({ id: 'region-glow', type: 'circle', source: 'regions', maxzoom: BREAKS[0] + 0.5, paint: {
      'circle-radius': ['+', 20, ['*', 1.8, ['sqrt', ['get', 'projects']]]], 'circle-color': rampExpr('#59607a'),
      'circle-blur': 1, 'circle-opacity': fade(0, BREAKS[0], 0.6) } });
    map.addLayer({ id: 'region-dot', type: 'circle', source: 'regions', maxzoom: BREAKS[0] + 0.5, paint: {
      'circle-radius': ['+', 7, ['*', 0.55, ['sqrt', ['get', 'projects']]]], 'circle-color': rampExpr('#59607a'),
      'circle-stroke-color': lit('#ffffff', 'rgba(255,255,255,0.6)'), 'circle-stroke-width': lit(3, 1.5),
      'circle-opacity': fade(0, BREAKS[0]), 'circle-stroke-opacity': fade(0, BREAKS[0]) } });

    // zones: heat-filled areas with their own coloured edge
    map.addLayer({ id: 'zone-fill', type: 'fill', source: 'zones', minzoom: BREAKS[0] - 0.5, maxzoom: BREAKS[2], paint: {
      'fill-color': rampExpr('#2a2f45'),
      'fill-opacity': ['interpolate', ['linear'], ['zoom'], BREAKS[0] - 0.5, 0, BREAKS[0], 0.42, BREAKS[1], 0.42, BREAKS[1] + 0.6, 0.12, BREAKS[2], 0] } });
    map.addLayer({ id: 'zone-edge-glow', type: 'line', source: 'zones', minzoom: BREAKS[0] - 0.5, maxzoom: BREAKS[2], paint: {
      'line-color': ['get', 'zone'], 'line-width': 10, 'line-blur': 9, 'line-opacity': fade(BREAKS[0], BREAKS[1], 0.45) } });
    map.addLayer({ id: 'zone-edge', type: 'line', source: 'zones', minzoom: BREAKS[0] - 0.5, maxzoom: BREAKS[2], paint: {
      'line-color': ['get', 'zone'], 'line-width': lit(4, 2), 'line-opacity': fade(BREAKS[0], BREAKS[1] + 0.8, 0.95) } });

    // pincodes: 3D columns, height = flats offered, colour = chosen metric
    map.addLayer({ id: 'columns', type: 'fill-extrusion', source: 'columns', minzoom: BREAKS[1] - 0.8, maxzoom: BREAKS[2] + 0.8, paint: {
      'fill-extrusion-color': lit('#ffffff', rampExpr('#3a4262')),
      'fill-extrusion-height': ['interpolate', ['linear'], ['zoom'], BREAKS[1] - 0.8, 0, BREAKS[1], ['get', 'h']],
      'fill-extrusion-opacity': ['interpolate', ['linear'], ['zoom'], BREAKS[2], 0.9, BREAKS[2] + 0.7, 0],
      'fill-extrusion-vertical-gradient': true } });

    // projects: glowing points coloured by schedule
    // pincode borders: a soft line under the blocks, then Google-style dashes at street level
    map.addLayer({ id: 'outline-line', type: 'line', source: 'outlines', minzoom: BREAKS[1] - 0.6, maxzoom: BREAKS[2] + 0.6, paint: {
      'line-color': ['get', 'zone'], 'line-width': 1.2,
      'line-opacity': ['interpolate', ['linear'], ['zoom'], BREAKS[1] - 0.6, 0, BREAKS[1], 0.55, BREAKS[2], 0.55, BREAKS[2] + 0.6, 0] } });
    map.addLayer({ id: 'outline-street-glow', type: 'line', source: 'outlines', minzoom: BREAKS[2], paint: {
      'line-color': '#ff6b6b', 'line-width': 8, 'line-blur': 6,
      'line-opacity': ['interpolate', ['linear'], ['zoom'], BREAKS[2], 0, BREAKS[2] + 0.6, 0.25] } });
    map.addLayer({ id: 'outline-street', type: 'line', source: 'outlines', minzoom: BREAKS[2], layout: { 'line-cap': 'round' }, paint: {
      'line-color': '#ff8a8a', 'line-width': 2.2, 'line-dasharray': [0.6, 1.6],
      'line-opacity': ['interpolate', ['linear'], ['zoom'], BREAKS[2], 0, BREAKS[2] + 0.6, 0.9] } });

    map.addLayer({ id: 'project-glow', type: 'circle', source: 'projects', minzoom: BREAKS[2] - 1, paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 12.5, 5, 16, 20], 'circle-color': ['get', 'colour'],
      'circle-blur': 1, 'circle-opacity': ['interpolate', ['linear'], ['zoom'], BREAKS[2] - 1, 0, BREAKS[2], 0.55] } });
    map.addLayer({ id: 'project-dot', type: 'circle', source: 'projects', minzoom: BREAKS[2] - 1, paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 12.5, 2.5, 16, ['+', 5, ['*', 0.35, ['sqrt', ['get', 'units']]]]],
      'circle-color': ['get', 'colour'], 'circle-stroke-color': lit('#ffffff', '#070910'), 'circle-stroke-width': lit(3, 1.2),
      'circle-opacity': ['interpolate', ['linear'], ['zoom'], BREAKS[2] - 1, 0, BREAKS[2], 1],
      'circle-stroke-opacity': ['interpolate', ['linear'], ['zoom'], BREAKS[2] - 1, 0, BREAKS[2], 1] } });

    // labels: data pills, collision-managed so a busy map stays readable
    const pill = (id, source, min, max, size, extra = {}) => map.addLayer({
      id, type: 'symbol', source, minzoom: min, maxzoom: max,
      layout: {
        'icon-image': 'pill', 'icon-text-fit': 'both', 'icon-text-fit-padding': [4, 8, 4, 8],
        'text-font': ['Noto Sans Bold'], 'text-size': size, 'text-line-height': 1.3, 'text-max-width': 30,
        // a pill with nothing to say on its second line stays one line tall
        'text-field': ['case', ['==', ['get', 'l2'], ''], ['format', ['get', 'l1'], { 'text-color': '#f4efe4' }],
          ['format',
            ['get', 'l1'], { 'text-color': '#f4efe4' }, '\n', {},
            ['get', 'l2'], { 'font-scale': 0.92, 'text-font': ['literal', ['Noto Sans Regular']], 'text-color': '#ffc93d' }, ' ', {},
            ['get', 'l3'], { 'font-scale': 0.92, 'text-color': ['case', ['==', ['get', 'up'], 1], '#3ddc97', '#ff6b6b'] }]],
        'symbol-sort-key': ['-', 0, ['coalesce', ['get', 'units'], 0]],
        ...extra,
      },
    });
    // On a phone, pills beside their bubbles run off the screen and the automatic placement drops
    // some, so each region of a close pair is placed by hand: the bigger one below, the other above.
    if (narrow) pill('region-label', 'regions', 0, BREAKS[0] + 0.2, 12, {
      'text-anchor': ['get', 'anchor'], 'text-offset': ['case', ['==', ['get', 'anchor'], 'top'], ['literal', [0, 1.6]], ['literal', [0, -1.6]]],
      'text-allow-overlap': true, 'icon-allow-overlap': true });
    else pill('region-label', 'regions', 0, BREAKS[0] + 0.2, 14, {
      'text-variable-anchor': ['top', 'bottom', 'left', 'right', 'top-left', 'bottom-right'], 'text-radial-offset': 2.2, 'text-justify': 'auto' });
    pill('zone-label', 'zone-centres', BREAKS[0] - 0.2, BREAKS[1] + 0.3, 13);
    pill('pin-label', 'pins', BREAKS[1], BREAKS[2] + 0.4, 12, { 'text-offset': [0, -1.4], 'text-anchor': 'bottom' });
    pill('project-label', 'projects', BREAKS[2] + 0.3, 24, 12, { 'text-offset': [0, -1.1], 'text-anchor': 'bottom' });
    map.setFilter('pin-label', ['>', ['get', 'projects'], 0]);

    const hoverable = { 'region-dot': 'regions', 'zone-fill': 'zones', columns: 'columns', 'project-dot': 'projects' };
    for (const [layer, source] of Object.entries(hoverable)) {
      map.on('mousemove', layer, (e) => {
        if (!canHover || levelOf(map.getZoom()) !== levelOfLayer(layer)) return;
        const f = pickTop(e.features, layer);
        if (!f) return;
        map.getCanvas().style.cursor = 'pointer';
        setHover(source, f.properties.id);
        pointer = e.point;
        hovered = recordOf(f.properties.kind, f.properties.id);
        stopOrbit();
      });
      map.on('mouseleave', layer, () => {
        map.getCanvas().style.cursor = '';
        setHover(null);
        hovered = null;
      });
      map.on('click', layer, (e) => {
        if (levelOf(map.getZoom()) !== levelOfLayer(layer)) return;
        const f = pickTop(e.features, layer);
        if (!f) return;
        picked = true;
        selected = recordOf(f.properties.kind, f.properties.id);
        if (free) {
          const d = byId.get(`${f.properties.kind}:${f.properties.id}`);
          const next = { region: 9.4, zone: 11.8, pincode: 14.8 }[f.properties.kind];
          if (next && d) map.flyTo({ center: [d.longitude, d.latitude], zoom: next, pitch: next > 11 ? 55 : 30, duration: 1400 });
        }
      });
    }
  }
  const levelOfLayer = (layer) => ({ 'region-dot': 0, 'zone-fill': 1, columns: 2, 'project-dot': 3 })[layer];

  // Overlapping zones: the smallest one under the pointer is the one meant.
  function pickTop(list, layer) {
    if (!list?.length) return null;
    if (layer !== 'zone-fill' || list.length === 1) return list[0];
    const size = (f) => { const c = f.geometry.coordinates[0]; let a = 0; for (let i = 1; i < c.length; i++) a += c[i - 1][0] * c[i][1] - c[i][0] * c[i - 1][1]; return Math.abs(a); };
    return [...list].sort((a, b) => size(a) - size(b))[0];
  }

  function setHover(source, id) {
    if (hoverKey) map.setFeatureState(hoverKey, { hover: false });
    hoverKey = source ? { source, id } : null;
    if (hoverKey) map.setFeatureState(hoverKey, { hover: true });
  }

  function recordOf(kind, id) {
    const d = byId.get(`${kind}:${id}`);
    if (!d) return null;
    if (kind === 'region') return { kind, data: d, title: d.name, sub: d.state };
    if (kind === 'zone') return { kind, data: d, title: `${d.name} zone`, sub: regionName(d.region_id) };
    if (kind === 'pincode') return { kind, data: d, title: `${d.id}${d.area ? ` · ${d.area}` : ''}`, sub: regionName(d.region_id) };
    return { kind, data: d, title: d.name, sub: d.locality ?? d.pincode, context: byId.get(`pincode:${d.pincode}`) };
  }

  // Re-colour for a new metric or currency without rebuilding the layers.
  function paint() {
    map.getSource('regions')?.setData(fc(features('region')));
    map.getSource('zones')?.setData(fc(features('zone')));
    map.getSource('zone-centres')?.setData(zoneCentres());
    map.getSource('pins')?.setData(fc(features('pincode')));
    map.getSource('columns')?.setData(columns());
    map.getSource('outlines')?.setData(outlines());
    map.getSource('projects')?.setData(fc(features('project')));
  }

  // Projects come from the server for the area in view, so the page never downloads the whole
  // registry. Views already fetched are remembered; the newest few thousand projects are kept.
  const fetchedViews = new Set();
  const KEEP = 6000;
  async function loadProjects() {
    if (!map || map.getZoom() < BREAKS[2] - 1) return;
    const b = map.getBounds();
    // Snap the view outwards to a 0.05° grid, so small pans reuse what was already fetched.
    const snap = (v, up) => (up ? Math.ceil(v * 20) : Math.floor(v * 20)) / 20;
    const box = { south: snap(b.getSouth(), false), west: snap(b.getWest(), false), north: snap(b.getNorth(), true), east: snap(b.getEast(), true) };
    const key = `${box.south},${box.west},${box.north},${box.east}`;
    if (fetchedViews.has(key)) return;
    fetchedViews.add(key);
    try {
      // (plain fetch, not the cached api(): views are remembered above, and the cache would keep every response)
      const r = await fetch(`/api/v1/map/projects?south=${box.south}&west=${box.west}&north=${box.north}&east=${box.east}`);
      if (!r.ok) throw new Error(String(r.status));
      const res = await r.json();
      const all = new Map(data.projects.map((p) => [p.id, p]));
      for (const p of res.projects) all.set(p.id, p);
      data.projects = [...all.values()].slice(-KEEP);
      for (const p of data.projects) byId.set(`project:${p.id}`, p);
      map.getSource('projects')?.setData(fc(features('project')));
      if (!picked) settle(true); // the orbit may already be turning; the new projects still need a card
    } catch (e) {
      fetchedViews.delete(key);
    }
  }

  // When the camera stops, the docked card shows whatever is nearest the middle, at this level.
  function settle(force = false) {
    zoom = map.getZoom();
    if (orbit && force !== true) return; // the slow orbit ends a move every frame; the middle has not changed
    const kind = LEVELS[levelOf(zoom)].id;
    if (picked && selected?.kind === kind) return;
    picked = false;
    const rows = data[PLURAL[kind]].filter((d) => kind === 'project' || d.projects);
    const c = map.getCenter();
    let best = null;
    for (const d of rows) {
      const dist = (d.longitude - c.lng) ** 2 + (d.latitude - c.lat) ** 2;
      if (!best || dist < best.dist) best = { d, dist };
    }
    if (best) selected = recordOf(kind, best.d.id);
  }

  // ---------------------------------------------------------------- the tour
  function plan() {
    const busiest = (rows, by) => [...rows].sort((a, b) => by(b) - by(a))[0];
    const box = (rows) => rows.reduce((b, d) => b.extend([d.longitude, d.latitude]), new maplibre.LngLatBounds([rows[0].longitude, rows[0].latitude], [rows[0].longitude, rows[0].latitude]));
    const live = data.regions.filter((r) => r.projects > 0);
    const out = [{ bounds: box(live.length ? live : data.regions), pitch: 0, bearing: 0, max: 7.6 }];
    const region = live.find((r) => r.id === 'pune-city') ?? busiest(live, (r) => r.projects);
    if (!region) return out;
    out.push({ bounds: box(data.pincodes.filter((p) => p.region_id === region.id)), pitch: 35, bearing: -8, min: 9.2, max: 10.3 });
    const zone = busiest(data.zones.filter((z) => z.region_id === region.id), (z) => z.projects);
    const zonePins = data.pincodes.filter((p) => p.region_id === region.id && p.zone_id === zone.zone_id);
    out.push({ bounds: box(zonePins), pitch: 58, bearing: -24, min: 11.3, max: 12.6, orbit: true });
    const pin = busiest(zonePins, (p) => p.projects);
    out.push({ centre: [pin.longitude, pin.latitude], zoom: 15, pitch: 55, bearing: 18, orbit: true });
    return out;
  }

  function go(index, animate = true) {
    const view = views[Math.min(index, views.length - 1)];
    if (!map || !view) return;
    picked = false;
    stopOrbit();
    let center = view.centre, z = view.zoom;
    const padding = room();
    if (view.bounds) {
      const cam = map.cameraForBounds(view.bounds, { padding, bearing: 0 }) ?? map.cameraForBounds(view.bounds, { padding: 20 });
      center = cam?.center ?? view.bounds.getCenter();
      z = clamp(cam?.zoom ?? 9, view.min ?? 3, view.max ?? 17);
    }
    // (padding on a camera move sticks to the map, so a point target is shifted with an offset instead)
    const offset = view.bounds ? [0, 0] : [(padding.left - padding.right) / 2, (padding.top - padding.bottom) / 2];
    const target = { center, zoom: z, pitch: view.pitch, bearing: view.bearing };
    if (animate) map.flyTo({ ...target, offset, duration: 2000, essential: true });
    else map.jumpTo(target);
    if (view.orbit && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      map.once('moveend', () => { if (!free && stage === index) startOrbit(); });
    }
  }

  // The open part of the map, between the floating panels, so the camera frames what matters there.
  function room() {
    const w = stageEl?.clientWidth ?? window.innerWidth, h = stageEl?.clientHeight ?? window.innerHeight;
    if (w < 960) return { top: 170, bottom: Math.min(240, Math.round(h * 0.3)), left: 70, right: 70 };
    return { top: 110, bottom: 60, left: Math.min(440, w * 0.3), right: Math.min(420, w * 0.3) };
  }

  // A slow drift around the target, so the 3D columns read as 3D.
  function startOrbit() {
    stopOrbit();
    let last = performance.now();
    const step = (now) => {
      map.setBearing(map.getBearing() + (now - last) * 0.0016);
      last = now;
      orbit = requestAnimationFrame(step);
    };
    orbit = requestAnimationFrame(step);
  }
  function stopOrbit() { cancelAnimationFrame(orbit); orbit = 0; }

  function lock(on) {
    for (const h of ['dragPan', 'scrollZoom', 'touchZoomRotate', 'doubleClickZoom', 'boxZoom', 'keyboard', 'dragRotate', 'touchPitch']) map?.[h]?.[on ? 'disable' : 'enable']();
  }
  function setFree(on) {
    free = on;
    stopOrbit();
    lock(!on);
    if (!on) go(stage);
  }

  // Beside the pointer, flipped to whichever side has room.
  const cardStyle = $derived.by(() => {
    if (!hovered || !pointer || !stageEl) return '';
    const w = stageEl.clientWidth, h = stageEl.clientHeight, cw = Math.min(340, w - 32);
    const left = pointer.x + 24 + cw > w ? pointer.x - 24 - cw : pointer.x + 24;
    const top = clamp(pointer.y - 70, 84, Math.max(84, h - cardH - 16));
    return `left:${Math.max(8, left)}px;top:${top}px;width:${cw}px`;
  });
</script>

<section class="quest" class:is-free={free} bind:this={section} id="map" aria-label="The map">
  <div class="quest__stage" bind:this={stageEl}>
    <div class="quest__map">
      <div class="map" bind:this={mapEl} aria-label="Map of RERA projects"></div>
      <div class="map__vignette" aria-hidden="true"></div>
    </div>

    <div class="quest__panel">
      <div class="quest__head">
        <p class="quest__level num">Level {level + 1} of {LEVELS.length}</p>
        <h2>{LEVELS[level].name}</h2>
      </div>
      <div class="track" aria-hidden="true">
        {#each LEVELS as l, i (l.id)}
          <span class="track__seg"><span class="track__fill" style:transform="scaleX({fill(i)})"></span></span>
        {/each}
      </div>
      <p class="quest__line">{LEVELS[level].line}</p>
      <ul class="unlocks" aria-label="Unlocked so far">
        {#each LEVELS.slice(0, level + 1) as l (l.id)}
          {#each l.unlocks as u (u)}
            <li class="chip chip--unlock">{u}</li>
          {/each}
        {/each}
      </ul>
      <div class="quest__foot">
        <button type="button" class="btn btn--small" aria-pressed={free} onclick={() => setFree(!free)}>
          {free ? 'Back to the tour' : 'Explore freely'}
        </button>
        <div class="levels" role="group" aria-label="Currency">
          <button type="button" class="key" class:key--on={currency === 'inr'} aria-pressed={currency === 'inr'} onclick={() => (currency = 'inr')}>₹</button>
          <button type="button" class="key" class:key--on={currency === 'usd'} aria-pressed={currency === 'usd'} onclick={() => (currency = 'usd')}>$</button>
        </div>
      </div>
      <p class="quest__hint">
        {#if free}Drag, zoom, right-drag to tilt. Click to dive in.{:else if stage < 3}Keep scrolling to go deeper.{:else}Street level. Try “Explore freely”.{/if}
      </p>
      {#if failed}<p class="quest__error" role="status">{failed}</p>{/if}
    </div>

    <div class="mapkey">
      {#if level < 3}
        <div class="mapkey__metrics" role="group" aria-label="Colour the map by">
          {#each METRICS as mt (mt.id)}
            <button type="button" class:is-on={metric === mt.id} aria-pressed={metric === mt.id} onclick={() => (metric = mt.id)}>{mt.name}</button>
          {/each}
        </div>
        <div class="mapkey__scale">
          <span class="mapkey__ramp" style:background="linear-gradient(90deg, {RAMP.join(', ')})"></span>
          <span class="mapkey__ends num"><span>{scale.lo}</span><span>{METRICS.find((x) => x.id === metric).hint}</span><span>{scale.hi}</span></span>
        </div>
        <p class="mapkey__none"><i></i>No {metric === 'supply' ? 'unit data' : 'price filed'} yet</p>
        {#if level === 1 && data?.zones.some((z) => z.boundary_estimated)}<p class="mapkey__note">Zone shapes are estimated from pincode centres.</p>{/if}
      {:else}
        <ul class="mapkey__dots">
          <li><i style:background={SCHEDULE_COLOUR.on_time}></i>On time</li>
          <li><i style:background={SCHEDULE_COLOUR.late}></i>Late</li>
          <li><i style:background={SCHEDULE_COLOUR.completed}></i>Completed</li>
        </ul>
      {/if}
      <p class="mapkey__zoom num">zoom {zoom.toFixed(1)}</p>
    </div>

    {#if hovered}
      <div class="quest__card is-hover" style={cardStyle} bind:clientHeight={cardH}>
        <InsightCard record={hovered} quarters={data?.quarters} {currency} />
      </div>
    {:else if selected}
      <div class="quest__card" class:is-sheet={narrow} class:is-open={narrow && expanded}>
        {#if narrow}
          <button type="button" class="sheet__handle" aria-expanded={expanded} onclick={() => (expanded = !expanded)}>
            <span aria-hidden="true"></span>{expanded ? 'Show less' : 'Show all insights'}
          </button>
        {/if}
        <InsightCard record={selected} quarters={data?.quarters} {currency} compact={narrow && !expanded} />
      </div>
    {/if}
  </div>
</section>

<script>
  import { onDestroy, onMount, untrack } from 'svelte';
  import { api } from './api.js';
  import { num } from './format.js';
  import InsightCard from './InsightCard.svelte';
  import { prefs } from './prefs.svelte.js';

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
  // One palette per theme and style. The map is rebuilt when either switch changes.
  const DARK_STYLE = 'https://tiles.openfreemap.org/styles/dark', LIGHT_STYLE = 'https://tiles.openfreemap.org/styles/positron';
  const GAME_ZONES = { central: '#f5b301', east: '#5fd38a', west: '#f06fb4', north: '#59c8f2', south: '#ff7a59' };
  const PALETTES = {
    'dark-game': {
      style: DARK_STYLE, ground: '#070910', water: '#0a1424', labels: 0.5, glow: true,
      ramp: ['#2a1d5c', '#5b2a8c', '#a3367f', '#e0575a', '#f99a3e', '#fde05a'], none: '#3a4262', zoneNone: '#2a2f45', regionNone: '#59607a',
      zones: GAME_ZONES, schedule: { on_time: '#3ddc97', early: '#3ddc97', completed: '#6aa8ff', late: '#ff5b5b', overdue: '#ff5b5b' },
      podium: '#2c3350', crown: '#f4efe4', hover: '#ffffff', stroke: 'rgba(255,255,255,0.6)', dotEdge: '#070910', street: '#ff8a8a',
      buildings: ['#1c2236', '#28304f', '#36426c', '#4a5a94'], light: '#dfe6ff',
      pill: { bg: 'rgba(10,12,20,0.92)', edge: 'rgba(255,255,255,0.18)', l1: '#f4efe4', l2: '#ffc93d', up: '#3ddc97', down: '#ff6b6b' },
    },
    'light-game': {
      style: LIGHT_STYLE, ground: '#f1efe9', water: '#cfe0ee', labels: 0.75, glow: false,
      ramp: ['#3b2a7a', '#6b3a9c', '#b2438a', '#e0575a', '#f29436', '#f2c230'], none: '#c9ccd6', zoneNone: '#d9dbe2', regionNone: '#a4a9b8',
      zones: { central: '#d99a00', east: '#2f9e5c', west: '#c83d86', north: '#2b8fc4', south: '#e0603c' },
      schedule: { on_time: '#1f9e66', early: '#1f9e66', completed: '#3a73d6', late: '#d93a3a', overdue: '#d93a3a' },
      podium: '#c9cdd8', crown: '#ffffff', hover: '#1a2233', stroke: 'rgba(20,30,50,0.55)', dotEdge: '#ffffff', street: '#d94a4a',
      buildings: ['#e6e3dc', '#dcd9d2', '#cfd0d4', '#bfc4cf'], light: '#ffffff',
      pill: { bg: 'rgba(255,255,255,0.95)', edge: 'rgba(20,30,50,0.18)', l1: '#1b2233', l2: '#9a5b00', up: '#178a57', down: '#c43434' },
    },
    'dark-classic': {
      style: DARK_STYLE, ground: '#12161d', water: '#16202c', labels: 0.65, glow: false,
      ramp: ['#1f3550', '#28507a', '#3570a3', '#4f91c6', '#7db3df', '#b9d7f0'], none: '#3a4250', zoneNone: '#262c36', regionNone: '#566070',
      zones: { central: '#c9b26b', east: '#7fb89a', west: '#b892b8', north: '#7fa8c9', south: '#c99a7f' },
      schedule: { on_time: '#5fb58a', early: '#5fb58a', completed: '#7fa8d9', late: '#d9776c', overdue: '#d9776c' },
      podium: '#2a313d', crown: '#d7e2ee', hover: '#ffffff', stroke: 'rgba(255,255,255,0.5)', dotEdge: '#12161d', street: '#d9776c',
      buildings: ['#1d232d', '#262e3a', '#313b4a', '#3e4a5d'], light: '#e6ecf5',
      pill: { bg: 'rgba(24,29,38,0.95)', edge: 'rgba(255,255,255,0.14)', l1: '#eef2f7', l2: '#b9d7f0', up: '#7fcfa2', down: '#e8968c' },
    },
    'light-classic': {
      style: LIGHT_STYLE, ground: '#f4f5f7', water: '#d6e3ef', labels: 0.8, glow: false,
      ramp: ['#d6e4f2', '#a9c4e0', '#6f9bc8', '#3f72ab', '#1f4e8c', '#0d2f5e'], none: '#d3d7de', zoneNone: '#e3e6eb', regionNone: '#a7aebb',
      zones: { central: '#8a7432', east: '#3d7f5c', west: '#7d4f7d', north: '#2f6690', south: '#9a5a3c' },
      schedule: { on_time: '#2e8b57', early: '#2e8b57', completed: '#2f6db5', late: '#c0392b', overdue: '#c0392b' },
      podium: '#cfd5de', crown: '#ffffff', hover: '#0d2f5e', stroke: 'rgba(20,30,50,0.5)', dotEdge: '#ffffff', street: '#c0392b',
      buildings: ['#e8eaee', '#dde1e7', '#cfd5de', '#bec6d2'], light: '#ffffff',
      pill: { bg: 'rgba(255,255,255,0.96)', edge: 'rgba(20,30,50,0.2)', l1: '#1b2233', l2: '#1f4e8c', up: '#2e7d4f', down: '#b23a2e' },
    },
  };
  const P = $derived(PALETTES[`${prefs.theme}-${prefs.mode}`]);
  let C = PALETTES['dark-game']; // the palette the current map was built with
  const classic = $derived(prefs.mode === 'classic');
  const PLAIN_NAMES = { region: 'City overview', zone: 'Zones', pincode: 'Pincodes', project: 'Projects' };
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
  // Flat sizes kept on the map. All four selected means no filter.
  const BHKS = [{ id: '1', name: '1 BHK' }, { id: '2', name: '2 BHK' }, { id: '3', name: '3 BHK' }, { id: '4', name: '4+ BHK' }];
  // Filter chips: nothing picked shows every size; picking 2 BHK shows only 2 BHK; picking more adds to it.
  let sizePicks = $state([]);
  const sizes = $derived(sizePicks.length && sizePicks.length < BHKS.length ? sizePicks : BHKS.map((b) => b.id));
  const filtered = $derived(sizes.length < BHKS.length);
  function toggleSize(id) { sizePicks = sizePicks.includes(id) ? sizePicks.filter((x) => x !== id) : [...sizePicks, id].sort(); }
  // Which projects count at all: registered from a year on, in any of the picked states. Unlike flat
  // sizes this is worked out on the server, so a change fetches the map's figures again.
  const STATUSES = [
    { id: 'active', name: 'Active', hint: 'Registration is in force' },
    { id: 'new', name: 'Just registered', hint: 'Registered in the last 90 days' },
    { id: 'due', name: 'Possession due', hint: 'Completion date in the next 6 months' },
    { id: 'extension', name: 'Extension applied', hint: 'The builder asked RERA for more time' },
    { id: 'completed', name: 'Completed', hint: 'Registration closed as completed' },
    { id: 'lapsed', name: 'Lapsed', hint: 'Registration ran out without completion' },
    { id: 'cancelled', name: 'Cancelled', hint: 'De-registered, revoked or held in abeyance' },
  ];
  const THIS_YEAR = new Date().getFullYear();
  const YEARS = Array.from({ length: THIS_YEAR - 2017 + 1 }, (_, i) => THIS_YEAR - i); // RERA registration began in 2017
  let since = $state('');
  let statusPicks = $state([]);
  const query = $derived.by(() => {
    const q = new URLSearchParams();
    if (since) q.set('since', since);
    if (statusPicks.length) q.set('status', statusPicks.join(','));
    return q.size ? `?${q}` : '';
  });
  let refiltering = $state(false);
  const matching = $derived(data?.regions.reduce((n, r) => n + r.projects, 0) ?? 0);
  function toggleStatus(id) { statusPicks = statusPicks.includes(id) ? statusPicks.filter((x) => x !== id) : [...statusPicks, id].sort(); }

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
  onDestroy(() => { cancelAnimationFrame(orbit); map?.remove(); document.documentElement.classList.remove('is-mapview'); });

  $effect(() => { if (mapEl && !map) start(); });
  // A new theme or style needs a new basemap and new layer colours: rebuild the map, keep the camera.
  $effect(() => { if (P !== C && map && ready) rebuild(); });
  // (paint also refreshes the open cards, so it runs untracked or it would re-trigger itself)
  $effect(() => { metric; currency; sizes; if (ready) untrack(paint); });
  $effect(() => { const q = query; if (ready) untrack(() => refilter(q)); });

  function track() {
    if (!section) return;
    const box = section.getBoundingClientRect();
    const run = box.height - window.innerHeight;
    progress = run > 0 ? clamp(-box.top / run, 0, 1) : 0;
    document.documentElement.classList.toggle('is-mapview', box.top <= 1 && box.bottom >= window.innerHeight - 1);
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

  // The same record, its figures re-added for the selected flat sizes only.
  // d.bhk[size] = [flats, unsold, priced flats, sum of their price per sq ft, projects];
  // d.bhk_projects[mask] = projects offering exactly that mix of sizes.
  function sized(d) {
    if (!filtered || !d) return d;
    const b = d.bhk ?? {};
    let flats = 0, unsold = 0, priced = 0, sum = 0;
    for (const k of sizes) { const r = b[k]; if (r) { flats += r[0]; unsold += r[1]; priced += r[2]; sum += r[3]; } }
    const ppsf = priced ? sum / priced : null;
    const rate = data?.inr_per_usd ?? 88;
    const out = { ...d, units_total: flats, units_unsold: unsold, price_per_sqft: ppsf ? { inr: ppsf, usd: ppsf / rate } : null, sized: true };
    if (d.bhk_projects) {
      const sel = sizes.reduce((m, k) => m | (1 << (Number(k) - 1)), 0);
      out.projects = Object.entries(d.bhk_projects).reduce((n, [mask, c]) => n + ((Number(mask) & sel) ? c : 0), 0);
    } else out.projects = flats ? 1 : 0;
    // the (sample) trend is scaled to end at the filtered price, so the card's line and number agree
    const was = d.price_per_sqft?.inr;
    if (d.trend?.price_per_sqft && was && ppsf) out.trend = { ...d.trend, price_per_sqft: d.trend.price_per_sqft.map((v) => (v * ppsf) / was) };
    return out;
  }
  // Rows for a level as the map shows them: sized, and for projects only those with the chosen sizes.
  const rowsOf = (kind) => {
    const rows = data[PLURAL[kind]].map(sized);
    return kind === 'project' && filtered ? rows.filter((d) => d.units_total > 0) : rows;
  };

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
    const rows = rowsOf(kind);
    const r = kind === 'project' ? null : ranks(rows.filter((d) => d.projects));
    if (kind === 'pincode') scale = { lo: r.lo, hi: r.hi };
    return rows.map((d) => {
      const props = { id: d.id, kind };
      let geometry = { type: 'Point', coordinates: [d.longitude, d.latitude] };
      if (kind === 'project') {
        Object.assign(props, {
          l1: (d.name ?? '').length > 26 ? `${d.name.slice(0, 25)}…` : d.name,
          l2: priceOf(d) ? `${priceOf(d)}/sqft` : d.units_total ? `${num(d.units_total)} ${d.units_total === 1 ? 'flat' : 'flats'}` : '',
          l3: '', up: 1,
          colour: C.schedule[d.schedule] ?? '#9aa3b5', units: d.units_total ?? 0,
        });
      } else {
        Object.assign(props, {
          t: d.projects ? r.at(metricValue(d)) : -1, projects: d.projects, units: d.units_total,
          l1: kind === 'region' ? d.name : kind === 'zone' ? `${regionName(d.region_id)} · ${d.name}` : `${d.id}${d.area ? ` ${d.area}` : ''}`,
          l2: d.projects ? [priceOf(d), kind === 'region' ? `· ${num(d.projects)} projects` : ''].filter(Boolean).join(' ') : 'Coming soon',
          l3: d.projects ? changeOf(d) : '', up: (d.trend?.price_qoq_pct ?? 0) >= 0 ? 1 : 0,
          zone: C.zones[d.zone_id] ?? C.zones.central,
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

  // ---------------------------------------------------------------- skylines
  // The same id always gives the same random numbers, so a pincode's skyline does not reshuffle on repaint.
  function seeded(seed) {
    let h = 2166136261;
    for (const ch of String(seed)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
    return () => {
      h = (h + 0x6d2b79f5) | 0;
      let t = Math.imul(h ^ (h >>> 15), 1 | h);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function inside([x, y], geom) {
    const polys = geom.type === 'Polygon' ? [geom.coordinates] : geom.type === 'MultiPolygon' ? geom.coordinates : [];
    const inRing = (ring) => {
      let hit = false;
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const [xi, yi] = ring[i], [xj, yj] = ring[j];
        if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) hit = !hit;
      }
      return hit;
    };
    return polys.some(([outer, ...holes]) => inRing(outer) && !holes.some(inRing));
  }

  // A footprint `half` metres from centre to side: a rotated square, or a round tower.
  function footprint(lng, lat, half, angle, round) {
    const dLat = 1 / 111320, dLng = 1 / (111320 * Math.cos((lat * Math.PI) / 180));
    const sides = round ? 14 : 4, r = round ? half : half * Math.SQRT2, out = [];
    for (let i = 0; i <= sides; i++) {
      const a = angle + (round ? 0 : Math.PI / 4) + (i / sides) * Math.PI * 2;
      out.push([lng + Math.cos(a) * r * dLng, lat + Math.sin(a) * r * dLat]);
    }
    return [out];
  }

  // One building: a wide podium, the tower, a set-back crown, and on the tallest a spire.
  function building(props, lng, lat, half, top, angle, round, spire) {
    const podium = top * 0.14;
    const tiers = [
      { tier: 'podium', half: half * 1.4, base: 0, top: podium },
      { tier: 'shaft', half, base: podium, top: top * 0.88 },
      { tier: 'crown', half: half * 0.68, base: top * 0.88, top },
    ];
    if (spire) tiers.push({ tier: 'crown', half: half * 0.14, base: top, top: top * 1.14 });
    return tiers.map((t) => ({
      type: 'Feature',
      properties: { ...props, tier: t.tier, base: t.base, top: t.top },
      geometry: { type: 'Polygon', coordinates: footprint(lng, lat, t.half, angle, round) },
    }));
  }

  // Each pincode becomes a small downtown: tallest tower in the middle, more towers for more projects,
  // the whole cluster as tall as the flats on offer. Towers stay inside the real postal outline.
  const skylines = () => fc(features('pincode').filter((f) => f.properties.projects).flatMap((f) => {
    const outline = byId.get(`pincode:${f.properties.id}`)?.boundary;
    const [cx, cy] = f.geometry.coordinates;
    const rand = seeded(f.properties.id);
    const units = f.properties.units ?? 0, H = 260 + 46 * Math.sqrt(units);
    const n = clamp(Math.round(2 + Math.sqrt(f.properties.projects) * 1.3), 3, 14);
    const R = 520 + 230 * Math.sqrt(n), grid = rand() * Math.PI / 2;
    const dLat = 1 / 111320, dLng = 1 / (111320 * Math.cos((cy * Math.PI) / 180));
    const out = [];
    for (let i = 0; i < n; i++) {
      let dist = i === 0 ? 0 : R * Math.sqrt(i / n) * (0.85 + 0.3 * rand());
      const a = i * 2.39996 + rand() * 0.6;
      let p = [cx + Math.cos(a) * dist * dLng, cy + Math.sin(a) * dist * dLat];
      for (let k = 0; outline && k < 4 && !inside(p, outline); k++) {
        dist /= 2;
        p = [cx + Math.cos(a) * dist * dLng, cy + Math.sin(a) * dist * dLat];
      }
      const falloff = 1 - 0.45 * (dist / R);
      const top = i === 0 ? H : H * falloff * (0.35 + 0.55 * rand());
      const half = (i === 0 ? 170 : 95 + 80 * rand()) * (0.8 + 0.4 * Math.min(1, n / 8));
      out.push(...building(f.properties, ...p, half, top, grid + (rand() - 0.5) * 0.15, rand() < 0.22, i === 0));
    }
    return out;
  }));

  // The ground each skyline stands on: the postal outline, or a hexagon where none is loaded.
  const plots = () => fc(features('pincode').filter((f) => f.properties.projects).map((f) => ({
    ...f, geometry: byId.get(`pincode:${f.properties.id}`)?.boundary ?? { type: 'Polygon', coordinates: [circle(...f.geometry.coordinates, 900, 6)] },
  })));

  // Each project as one building: footprint and height grow with its flats.
  const towers = () => fc(features('project').flatMap((f) => {
    const rand = seeded(f.properties.id), u = Math.sqrt(f.properties.units || 20);
    return building(f.properties, ...f.geometry.coordinates, 18 + 1.6 * u, 40 + 9 * u, rand() * Math.PI / 2, rand() < 0.2, u > 18);
  }));
  // Every loaded outline, for the thin borders (pincodes without projects included).
  const outlines = () => fc((data?.pincodes ?? []).filter((p) => p.boundary).map((p) => ({
    type: 'Feature', properties: { id: p.id, zone: C.zones[p.zone_id] ?? C.zones.central, projects: p.projects }, geometry: p.boundary,
  })));
  const rampExpr = (fallback, ramp = C.ramp) => ['case', ['<', ['get', 't'], 0], fallback,
    ['interpolate', ['linear'], ['get', 't'], ...ramp.flatMap((c, i) => [i / (ramp.length - 1), c])]];
  // The same ramp mixed toward white, for the lit tops of the towers.
  const mix = (hex, k) => `#${[1, 3, 5].map((i) => Math.round(parseInt(hex.slice(i, i + 2), 16) * (1 - k) + 255 * k).toString(16).padStart(2, '0')).join('')}`;

  // ---------------------------------------------------------------- map
  function pillImage() {
    const s = 2, w = 40 * s, h = 28 * s, r = 9 * s;
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d');
    g.fillStyle = C.pill.bg;
    g.strokeStyle = C.pill.edge;
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
    if (!watching) { watching = true; small.addEventListener('change', (e) => (narrow = e.matches)); }
    C = P;
    map = new maplibre.Map({ container: mapEl, style: C.style, center: [75.2, 16.8], zoom: 5.2, maxPitch: 70, attributionControl: { compact: true } });
    lock(true);
    map.addControl(new maplibre.NavigationControl({ visualizePitch: true }), 'bottom-left');
    try {
      const q = query;
      const [res] = await Promise.all([api(`/v1/map/insights${q}`), new Promise((r) => map.once('load', r))]);
      shown = q;
      adopt(res);
    } catch (e) {
      failed = 'The map could not load its figures. Is the API running?';
      return;
    }
    tune();
    layers();
    views = plan();
    map.on('move', () => (zoom = map.getZoom()));
    map.on('moveend', settle);
    map.on('moveend', () => { if (!orbit) loadProjects(); });
    map.on('dragstart', stopOrbit);
    ready = true;
    track();
    if (camera) { lock(!free); map.jumpTo(camera); camera = null; loadProjects(); }
    else go(stage, false);
  }

  let watching = false, camera = null;

  // Take a fresh payload: projects are filled per view by loadProjects(), once zoomed in that far.
  // (a copy, because api() keeps the response and the projects list changes)
  function adopt(res) {
    data = { ...res, projects: [] };
    byId.clear();
    fetchedViews.clear();
    for (const kind of Object.keys(PLURAL)) for (const d of data[PLURAL[kind]]) byId.set(`${kind}:${d.id}`, d);
  }

  // The year or status filter changed: swap in the figures for it and fetch projects again.
  let shown = '';
  async function refilter(q) {
    if (q === shown) return;
    shown = q;
    refiltering = true;
    try {
      const res = await api(`/v1/map/insights${q}`);
      if (q !== shown || !map) return;
      adopt(res);
      paint();
      picked = false;
      settle(true);
      loadProjects();
    } catch (e) {
      failed = 'The map could not load figures for that filter. Try again.';
    } finally {
      if (q === shown) refiltering = false;
    }
  }
  function rebuild() {
    camera = { center: map.getCenter(), zoom: map.getZoom(), pitch: map.getPitch(), bearing: map.getBearing() };
    stopOrbit(); stopSteer();
    hoverKey = null; hovered = null;
    fetchedViews.clear();
    ready = false;
    map.remove();
    map = null;
    start();
  }

  // Quieter basemap so the data glows: night ground, dimmer labels, 3D buildings at street level.
  function tune() {
    for (const l of map.getStyle().layers) {
      if (l.type === 'background') map.setPaintProperty(l.id, 'background-color', C.ground);
      if (l.type === 'symbol' && l.layout?.['text-field']) map.setPaintProperty(l.id, 'text-opacity', C.labels);
      if (l.type === 'fill' && l['source-layer'] === 'water') map.setPaintProperty(l.id, 'fill-color', C.water);
    }
    const firstLabel = map.getStyle().layers.find((l) => l.type === 'symbol')?.id;
    // The real city around the projects: taller buildings catch a little more light.
    map.addLayer({
      id: 'buildings-3d', type: 'fill-extrusion', source: 'openmaptiles', 'source-layer': 'building', minzoom: 13.6,
      paint: {
        'fill-extrusion-color': ['interpolate', ['linear'], ['coalesce', ['get', 'render_height'], 8], 0, C.buildings[0], 20, C.buildings[1], 60, C.buildings[2], 150, C.buildings[3]],
        'fill-extrusion-height': ['interpolate', ['linear'], ['zoom'], 13.6, 0, 14.6, ['coalesce', ['get', 'render_height'], 8]],
        'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
        'fill-extrusion-opacity': ['interpolate', ['linear'], ['zoom'], 13.6, 0, 14.6, 0.85],
        'fill-extrusion-vertical-gradient': true,
      },
    }, firstLabel);
    map.setLight({ anchor: 'map', position: [1.4, 210, 35], color: C.light, intensity: 0.45 });
    const { img, opts } = pillImage();
    map.addImage('pill', img, opts);
  }

  function layers() {
    map.addSource('regions', { type: 'geojson', data: fc(features('region')), promoteId: 'id' });
    map.addSource('zones', { type: 'geojson', data: fc(features('zone')), promoteId: 'id' });
    map.addSource('zone-centres', { type: 'geojson', data: zoneCentres(), promoteId: 'id' });
    map.addSource('pins', { type: 'geojson', data: fc(features('pincode')), promoteId: 'id' });
    map.addSource('columns', { type: 'geojson', data: skylines(), promoteId: 'id' });
    map.addSource('plots', { type: 'geojson', data: plots(), promoteId: 'id' });
    map.addSource('project-towers', { type: 'geojson', data: towers(), promoteId: 'id' });
    map.addSource('outlines', { type: 'geojson', data: outlines(), promoteId: 'id' });
    map.addSource('projects', { type: 'geojson', data: fc(features('project')), promoteId: 'id' });

    const fade = (a, b, max = 1) => (a > 0
      ? ['interpolate', ['linear'], ['zoom'], a - 0.4, 0, a, max, b, max, b + 0.4, 0]
      : ['interpolate', ['linear'], ['zoom'], b, max, b + 0.4, 0]);
    const lit = (on, off) => ['case', ['boolean', ['feature-state', 'hover'], false], on, off];

    // regions: glowing bubbles
    if (C.glow) map.addLayer({ id: 'region-glow', type: 'circle', source: 'regions', maxzoom: BREAKS[0] + 0.5, paint: {
      'circle-radius': ['+', 20, ['*', 1.8, ['sqrt', ['get', 'projects']]]], 'circle-color': rampExpr(C.regionNone),
      'circle-blur': 1, 'circle-opacity': fade(0, BREAKS[0], 0.6) } });
    map.addLayer({ id: 'region-dot', type: 'circle', source: 'regions', maxzoom: BREAKS[0] + 0.5, paint: {
      'circle-radius': ['+', 7, ['*', 0.55, ['sqrt', ['get', 'projects']]]], 'circle-color': rampExpr(C.regionNone),
      'circle-stroke-color': lit(C.hover, C.stroke), 'circle-stroke-width': lit(3, 1.5),
      'circle-opacity': fade(0, BREAKS[0]), 'circle-stroke-opacity': fade(0, BREAKS[0]) } });

    // zones: heat-filled areas with their own coloured edge
    map.addLayer({ id: 'zone-fill', type: 'fill', source: 'zones', minzoom: BREAKS[0] - 0.5, maxzoom: BREAKS[2], paint: {
      'fill-color': rampExpr(C.zoneNone),
      'fill-opacity': ['interpolate', ['linear'], ['zoom'], BREAKS[0] - 0.5, 0, BREAKS[0], 0.42, BREAKS[1], 0.42, BREAKS[1] + 0.6, 0.12, BREAKS[2], 0] } });
    if (C.glow) map.addLayer({ id: 'zone-edge-glow', type: 'line', source: 'zones', minzoom: BREAKS[0] - 0.5, maxzoom: BREAKS[2], paint: {
      'line-color': ['get', 'zone'], 'line-width': 10, 'line-blur': 9, 'line-opacity': fade(BREAKS[0], BREAKS[1], 0.45) } });
    map.addLayer({ id: 'zone-edge', type: 'line', source: 'zones', minzoom: BREAKS[0] - 0.5, maxzoom: BREAKS[2], paint: {
      'line-color': ['get', 'zone'], 'line-width': lit(4, 2), 'line-opacity': fade(BREAKS[0], BREAKS[1] + 0.8, 0.95) } });

    // pincodes: a lit plot of ground, and on it a skyline. Height = flats offered, colour = chosen metric.
    const rise = (prop, from, to) => ['interpolate', ['linear'], ['zoom'], from, 0, to, ['get', prop]];
    map.addLayer({ id: 'plot-fill', type: 'fill', source: 'plots', minzoom: BREAKS[1] - 0.8, maxzoom: BREAKS[2] + 0.8, paint: {
      'fill-color': rampExpr(C.none),
      'fill-opacity': ['interpolate', ['linear'], ['zoom'], BREAKS[1] - 0.8, 0, BREAKS[1], 0.14, BREAKS[2], 0.14, BREAKS[2] + 0.7, 0] } });
    map.addLayer({ id: 'columns', type: 'fill-extrusion', source: 'columns', minzoom: BREAKS[1] - 0.8, maxzoom: BREAKS[2] + 0.8, paint: {
      'fill-extrusion-color': lit(C.hover, ['match', ['get', 'tier'], 'podium', C.podium, 'crown', rampExpr(C.none, C.ramp.map((c) => mix(c, 0.35))), rampExpr(C.none)]),
      'fill-extrusion-height': rise('top', BREAKS[1] - 0.8, BREAKS[1]),
      'fill-extrusion-base': rise('base', BREAKS[1] - 0.8, BREAKS[1]),
      'fill-extrusion-opacity': ['interpolate', ['linear'], ['zoom'], BREAKS[2], 0.95, BREAKS[2] + 0.7, 0],
      'fill-extrusion-vertical-gradient': true } });

    // projects: one building each, coloured by schedule, rising as the skylines fade
    map.addLayer({ id: 'project-towers', type: 'fill-extrusion', source: 'project-towers', minzoom: BREAKS[2] - 0.6, paint: {
      'fill-extrusion-color': lit(C.hover, ['match', ['get', 'tier'], 'podium', C.podium, 'crown', C.crown, ['get', 'colour']]),
      'fill-extrusion-height': rise('top', BREAKS[2] - 0.6, BREAKS[2] + 0.4),
      'fill-extrusion-base': rise('base', BREAKS[2] - 0.6, BREAKS[2] + 0.4),
      'fill-extrusion-opacity': ['interpolate', ['linear'], ['zoom'], BREAKS[2] - 0.6, 0, BREAKS[2], 0.92],
      'fill-extrusion-vertical-gradient': true } });

    // projects: glowing points coloured by schedule
    // pincode borders: a soft line under the blocks, then Google-style dashes at street level
    map.addLayer({ id: 'outline-line', type: 'line', source: 'outlines', minzoom: BREAKS[1] - 0.6, maxzoom: BREAKS[2] + 0.6, paint: {
      'line-color': ['get', 'zone'], 'line-width': 1.2,
      'line-opacity': ['interpolate', ['linear'], ['zoom'], BREAKS[1] - 0.6, 0, BREAKS[1], 0.55, BREAKS[2], 0.55, BREAKS[2] + 0.6, 0] } });
    if (C.glow) map.addLayer({ id: 'outline-street-glow', type: 'line', source: 'outlines', minzoom: BREAKS[2], paint: {
      'line-color': '#ff6b6b', 'line-width': 8, 'line-blur': 6,
      'line-opacity': ['interpolate', ['linear'], ['zoom'], BREAKS[2], 0, BREAKS[2] + 0.6, 0.25] } });
    map.addLayer({ id: 'outline-street', type: 'line', source: 'outlines', minzoom: BREAKS[2], layout: { 'line-cap': 'round' }, paint: {
      'line-color': C.street, 'line-width': 2.2, 'line-dasharray': [0.6, 1.6],
      'line-opacity': ['interpolate', ['linear'], ['zoom'], BREAKS[2], 0, BREAKS[2] + 0.6, 0.9] } });

    if (C.glow) map.addLayer({ id: 'project-glow', type: 'circle', source: 'projects', minzoom: BREAKS[2] - 1, paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 12.5, 5, 14, 14, 16, 26], 'circle-color': ['get', 'colour'], 'circle-pitch-alignment': 'map',
      'circle-blur': 1, 'circle-opacity': ['interpolate', ['linear'], ['zoom'], BREAKS[2] - 1, 0, BREAKS[2], 0.55] } });
    map.addLayer({ id: 'project-dot', type: 'circle', source: 'projects', minzoom: BREAKS[2] - 1, paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 12.5, 2.5, 14, 4, 16, 3],
      'circle-color': ['get', 'colour'], 'circle-stroke-color': lit(C.hover, C.dotEdge), 'circle-stroke-width': lit(3, 1.2),
      'circle-opacity': ['interpolate', ['linear'], ['zoom'], BREAKS[2] - 1, 0, BREAKS[2], 1],
      'circle-stroke-opacity': ['interpolate', ['linear'], ['zoom'], BREAKS[2] - 1, 0, BREAKS[2], 1] } });

    // labels: data pills, collision-managed so a busy map stays readable
    const pill = (id, source, min, max, size, extra = {}) => map.addLayer({
      id, type: 'symbol', source, minzoom: min, maxzoom: max,
      layout: {
        'icon-image': 'pill', 'icon-text-fit': 'both', 'icon-text-fit-padding': [4, 8, 4, 8],
        'text-font': ['Noto Sans Bold'], 'text-size': size, 'text-line-height': 1.3, 'text-max-width': 30,
        // a pill with nothing to say on its second line stays one line tall
        'text-field': ['case', ['==', ['get', 'l2'], ''], ['format', ['get', 'l1'], { 'text-color': C.pill.l1 }],
          ['format',
            ['get', 'l1'], { 'text-color': C.pill.l1 }, '\n', {},
            ['get', 'l2'], { 'font-scale': 0.92, 'text-font': ['literal', ['Noto Sans Regular']], 'text-color': C.pill.l2 }, ' ', {},
            ['get', 'l3'], { 'font-scale': 0.92, 'text-color': ['case', ['==', ['get', 'up'], 1], C.pill.up, C.pill.down] }]],
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
    // below the building, so the pill never hides the tower it names
    pill('project-label', 'projects', BREAKS[2] + 0.3, 24, 12, { 'text-offset': [0, 1.2], 'text-anchor': 'top' });
    map.setFilter('pin-label', ['>', ['get', 'projects'], 0]);

    const hoverable = { 'region-dot': 'regions', 'zone-fill': 'zones', columns: 'columns', 'project-towers': 'projects', 'project-dot': 'projects' };
    for (const [layer, source] of Object.entries(hoverable)) {
      map.on('mousemove', layer, (e) => {
        if (!canHover || levelOf(map.getZoom()) !== levelOfLayer(layer)) return;
        const f = pickTop(e.features, layer);
        if (!f) return;
        map.getCanvas().style.cursor = 'pointer';
        keepCard();
        stopOrbit();
        // the card stays where it opened, so the pointer can travel into it and use its link
        if (hovered?.kind === f.properties.kind && hovered?.data?.id === f.properties.id) return;
        setHover(source, f.properties.id);
        pointer = e.point;
        hovered = recordOf(f.properties.kind, f.properties.id);
      });
      map.on('mouseleave', layer, () => {
        map.getCanvas().style.cursor = '';
        dropCard();
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
  // A hover card lingers briefly after the pointer leaves its feature, and stays while the pointer is on it.
  let cardTimer = 0;
  function keepCard() { clearTimeout(cardTimer); }
  function dropCard(now = false) {
    clearTimeout(cardTimer);
    const go = () => { setHover(null); hovered = null; };
    if (now) go(); else cardTimer = setTimeout(go, 380);
  }
  const levelOfLayer = (layer) => ({ 'region-dot': 0, 'zone-fill': 1, columns: 2, 'project-towers': 3, 'project-dot': 3 })[layer];

  // Overlapping zones: the smallest one under the pointer is the one meant.
  function pickTop(list, layer) {
    if (!list?.length) return null;
    if (layer !== 'zone-fill' || list.length === 1) return list[0];
    const size = (f) => { const c = f.geometry.coordinates[0]; let a = 0; for (let i = 1; i < c.length; i++) a += c[i - 1][0] * c[i][1] - c[i][0] * c[i - 1][1]; return Math.abs(a); };
    return [...list].sort((a, b) => size(a) - size(b))[0];
  }

  // A project is drawn twice (its building and its dot), so both light up together.
  const TWIN = { projects: 'project-towers' };
  function setHover(source, id) {
    for (const k of hoverKey ?? []) map.setFeatureState(k, { hover: false });
    hoverKey = source ? [source, TWIN[source]].filter(Boolean).map((s) => ({ source: s, id })) : null;
    for (const k of hoverKey ?? []) map.setFeatureState(k, { hover: true });
  }

  function recordOf(kind, id) {
    const d = sized(byId.get(`${kind}:${id}`));
    if (!d) return null;
    if (kind === 'region') return { kind, data: d, title: d.name, sub: d.state };
    if (kind === 'zone') return { kind, data: d, title: `${d.name} zone`, sub: regionName(d.region_id) };
    if (kind === 'pincode') return { kind, data: d, title: `${d.id}${d.area ? ` · ${d.area}` : ''}`, sub: regionName(d.region_id) };
    return { kind, data: d, title: d.name, sub: d.locality ?? d.pincode, context: sized(byId.get(`pincode:${d.pincode}`)) };
  }

  // Re-colour for a new metric or currency without rebuilding the layers.
  function paint() {
    map.getSource('regions')?.setData(fc(features('region')));
    map.getSource('zones')?.setData(fc(features('zone')));
    map.getSource('zone-centres')?.setData(zoneCentres());
    map.getSource('pins')?.setData(fc(features('pincode')));
    map.getSource('columns')?.setData(skylines());
    map.getSource('plots')?.setData(plots());
    map.getSource('project-towers')?.setData(towers());
    map.getSource('outlines')?.setData(outlines());
    map.getSource('projects')?.setData(fc(features('project')));
    if (selected) selected = recordOf(selected.kind, selected.data.id);
    if (hovered) hovered = recordOf(hovered.kind, hovered.data.id);
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
      const q = shown;
      const r = await fetch(`/api/v1/map/projects?south=${box.south}&west=${box.west}&north=${box.north}&east=${box.east}${q ? `&${q.slice(1)}` : ''}`);
      if (!r.ok) throw new Error(String(r.status));
      const res = await r.json();
      if (q !== shown) return; // the filter changed while this view was loading
      const all = new Map(data.projects.map((p) => [p.id, p]));
      for (const p of res.projects) all.set(p.id, p);
      data.projects = [...all.values()].slice(-KEEP);
      for (const p of data.projects) byId.set(`project:${p.id}`, p);
      map.getSource('projects')?.setData(fc(features('project')));
      map.getSource('project-towers')?.setData(towers());
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
    const rows = rowsOf(kind).filter((d) => kind === 'project' || d.projects);
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
    if (w < 960) return { top: 110, bottom: 130, left: 40, right: 40 };
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
    if (!on) { stopSteer(); go(stage); return; }
    // the tour starts flat at the top level; exploring should feel 3D straight away
    if (map && map.getPitch() < 25) map.easeTo({ pitch: 55, bearing: map.getBearing() - 20, duration: 900 });
  }

  // ---------------------------------------------------------------- camera pad
  // Hold a button to keep turning or tilting; a quick tap (or Enter) moves one step.
  // Mouse users can also right-drag or Ctrl-drag; this is for trackpads and phones.
  const STEER = { left: [-1, 0], right: [1, 0], up: [0, 1], down: [0, -1] };
  let steering = 0, steerFrom = 0;
  function startSteer(dir, e) {
    if (!map) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    stopOrbit(); stopSteer();
    const [db, dp] = STEER[dir];
    let last = performance.now();
    steerFrom = last;
    const step = (now) => {
      const dt = Math.min(48, now - last); last = now;
      map.jumpTo({ bearing: map.getBearing() + db * dt * 0.08, pitch: clamp(map.getPitch() + dp * dt * 0.045, 0, 70) });
      steering = requestAnimationFrame(step);
    };
    steering = requestAnimationFrame(step);
  }
  function endSteer(dir) {
    const quick = steering && performance.now() - steerFrom < 180;
    stopSteer();
    if (quick) nudge(dir);
  }
  function stopSteer() { cancelAnimationFrame(steering); steering = 0; }
  function nudge(dir) {
    const [db, dp] = STEER[dir];
    map?.easeTo({ bearing: map.getBearing() + db * 30, pitch: clamp(map.getPitch() + dp * 15, 0, 70), duration: 400 });
  }
  let pitched = $state(false);
  $effect(() => { if (ready) { const on = () => (pitched = map.getPitch() > 5); map.on('pitch', on); on(); } });
  function flat() {
    map?.easeTo(pitched ? { pitch: 0, bearing: 0, duration: 700 } : { pitch: 55, bearing: map.getBearing() - 20, duration: 700 });
  }

  // Swipe the sheet up to open it, down to close it; a tap toggles it (handled by the click).
  let swipeY = 0, swiped = false;
  function swipeStart(e) { swipeY = e.clientY; swiped = false; }
  function swipeEnd(e) {
    const dy = e.clientY - swipeY;
    if (Math.abs(dy) < 24) return;
    swiped = true;
    expanded = dy < 0;
    setTimeout(() => (swiped = false), 50);
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
        <p class="quest__level num">{classic ? 'Step' : 'Level'} {level + 1} of {LEVELS.length}</p>
        <h2>{classic ? PLAIN_NAMES[LEVELS[level].id] : LEVELS[level].name}</h2>
      </div>
      <div class="track" aria-hidden="true">
        {#each LEVELS as l, i (l.id)}
          <span class="track__seg"><span class="track__fill" style:transform="scaleX({fill(i)})"></span></span>
        {/each}
      </div>
      <p class="quest__line">{LEVELS[level].line}</p>
      <ul class="unlocks" aria-label={classic ? 'Shown at this step' : 'Unlocked so far'}>
        {#each LEVELS.slice(0, level + 1) as l (l.id)}
          {#each l.unlocks as u (u)}
            <li class="chip chip--unlock">{u}</li>
          {/each}
        {/each}
      </ul>
      <div class="quest__foot">
        <button type="button" class="btn btn--small" aria-pressed={free} onclick={() => setFree(!free)}>
          {free ? (narrow ? 'Tour' : 'Back to the tour') : narrow ? 'Explore' : 'Explore freely'}
        </button>
        <div class="levels" role="group" aria-label="Currency">
          <button type="button" class="key" class:key--on={currency === 'inr'} aria-pressed={currency === 'inr'} onclick={() => (currency = 'inr')}>₹</button>
          <button type="button" class="key" class:key--on={currency === 'usd'} aria-pressed={currency === 'usd'} onclick={() => (currency = 'usd')}>$</button>
        </div>
      </div>
      <p class="quest__hint">
        {#if free}Drag to move. Turn and tilt with the buttons, or right-drag. Click to dive in.{:else if stage < 3}Keep scrolling to go deeper.{:else}Street level. Try “Explore freely”.{/if}
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
          <span class="mapkey__ramp" style:background="linear-gradient(90deg, {P.ramp.join(', ')})"></span>
          <span class="mapkey__ends num"><span>{scale.lo}</span><span>{METRICS.find((x) => x.id === metric).hint}</span><span>{scale.hi}</span></span>
        </div>
        <p class="mapkey__none"><i></i>No {metric === 'supply' ? 'unit data' : 'price filed'} yet</p>
        {#if level === 1 && data?.zones.some((z) => z.boundary_estimated)}<p class="mapkey__note">Zone shapes are estimated from pincode centres.</p>{/if}
      {:else}
        <ul class="mapkey__dots">
          <li><i style:background={P.schedule.on_time}></i>On time</li>
          <li><i style:background={P.schedule.late}></i>Late</li>
          <li><i style:background={P.schedule.completed}></i>Completed</li>
        </ul>
      {/if}
      <div class="sizes" role="group" aria-label="Flat sizes shown">
        <p class="sizes__label">Flat size {#if filtered}<button type="button" class="sizes__all" onclick={() => (sizePicks = [])}>Show all</button>{/if}</p>
        <div class="sizes__chips">
          {#each BHKS as b (b.id)}
            <button type="button" class="chiptog" class:is-on={sizePicks.includes(b.id) && filtered} aria-pressed={sizePicks.includes(b.id) && filtered} onclick={() => toggleSize(b.id)}>{b.name}</button>
          {/each}
        </div>
        {#if filtered}<p class="sizes__note">Sizes are estimated from carpet area. Projects that filed no flat sizes are hidden.</p>{/if}
      </div>
      <div class="sizes" role="group" aria-label="Registration year and status">
        <p class="sizes__label">Registered {#if query}<button type="button" class="sizes__all" onclick={() => { since = ''; statusPicks = []; }}>Show all</button>{/if}</p>
        <select class="yearpick" class:is-on={since} bind:value={since} aria-label="Registered in or after">
          <option value="">Any year</option>
          {#each YEARS as y (y)}<option value={String(y)}>{y} or later</option>{/each}
        </select>
        <div class="sizes__chips sizes__chips--status">
          {#each STATUSES as st (st.id)}
            <button type="button" class="chiptog" class:is-on={statusPicks.includes(st.id)} aria-pressed={statusPicks.includes(st.id)} title={st.hint} onclick={() => toggleStatus(st.id)}>{st.name}</button>
          {/each}
        </div>
        {#if query}<p class="sizes__note" aria-live="polite">{refiltering ? 'Updating the map…' : `${num(matching)} projects match.${statusPicks.length > 1 ? ' A project can be in more than one state.' : ''}`}</p>{/if}
      </div>
      <p class="mapkey__zoom num">zoom {zoom.toFixed(1)}</p>
    </div>

    {#if free}
      <div class="campad" role="group" aria-label="Camera">
        {#each [['left', '⟲', 'Turn left'], ['up', '▲', 'Tilt more'], ['down', '▼', 'Tilt less'], ['right', '⟳', 'Turn right']] as [dir, icon, label] (dir)}
          <button type="button" class="campad__btn" aria-label={label} title={label}
            onpointerdown={(e) => startSteer(dir, e)} onpointerup={() => endSteer(dir)}
            onpointercancel={stopSteer} onlostpointercapture={stopSteer}
            onclick={(e) => { if (e.detail === 0) nudge(dir); }}>{icon}</button>
        {/each}
        <button type="button" class="campad__btn campad__mode" aria-pressed={!pitched} onclick={flat}>{pitched ? '2D' : '3D'}</button>
      </div>
    {/if}

    {#if hovered}
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div class="quest__card is-hover" style={cardStyle} bind:clientHeight={cardH} onmouseenter={keepCard} onmouseleave={() => dropCard()}>
        <InsightCard record={hovered} quarters={data?.quarters} {currency} {sizes} />
      </div>
    {:else if selected}
      <div class="quest__card" class:is-sheet={narrow} class:is-open={narrow && expanded}>
        {#if narrow}
          <!-- The phone sheet: a one-line peek over the map; swipe up or tap for everything. -->
          <button type="button" class="sheet__handle" aria-expanded={expanded} aria-label={expanded ? 'Show less' : 'Show all details'}
            onpointerdown={swipeStart} onpointerup={swipeEnd} onclick={() => { if (!swiped) expanded = !expanded; }}>
            <span class="sheet__grip" aria-hidden="true"></span>
            {#if level < 3}
              <span class="sheet__scale" aria-hidden="true"><span class="num">{scale.lo}</span><i style:background="linear-gradient(90deg, {P.ramp.join(', ')})"></i><span class="num">{scale.hi}</span></span>
            {:else}
              <span class="sheet__dots" aria-hidden="true"><i style:background={P.schedule.on_time}></i>On time<i style:background={P.schedule.late}></i>Late<i style:background={P.schedule.completed}></i>Done</span>
            {/if}
            <span class="sheet__more">{expanded ? 'Less' : 'Details'}<span aria-hidden="true">{expanded ? ' ▾' : ' ▴'}</span></span>
          </button>
          {#if expanded}
            <InsightCard record={selected} quarters={data?.quarters} {currency} {sizes} />
          {:else}
            <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
            <div class="sheet__peek" onpointerdown={swipeStart} onpointerup={swipeEnd} onclick={(e) => { if (!swiped && !e.target.closest('a')) expanded = true; }}>
              <InsightCard record={selected} quarters={data?.quarters} {currency} {sizes} peek />
            </div>
          {/if}
        {:else}
          <InsightCard record={selected} quarters={data?.quarters} {currency} {sizes} />
        {/if}
      </div>
    {/if}
  </div>
</section>

<script>
  import { onMount } from 'svelte';
  import { api } from './api.js';

  // The hero is the data itself: every registered project glows on a night map, new ones pulse,
  // and the headline cycles through what Subak finds in your pincode.
  const WORDS = ['new building', 'real price', 'stalled project', 'fresh lead', 'court case'];
  const GLITCH_MS = 380;

  let canvas = $state();
  let data = $state(null);
  let word = $state(0);
  let glitching = $state(false);
  let counted = $state(0); // 0..1, drives the count-up
  let error = $state('');

  const t = $derived(data?.totals);
  const ease = (x) => 1 - (1 - x) ** 3;
  const count = (v) => Math.round((v ?? 0) * ease(counted));
  const crore = (v) => Math.round(((v ?? 0) / 1e7) * ease(counted)).toLocaleString('en-IN');

  // Facts for the ticker, all read from the loaded data, none invented.
  const facts = $derived.by(() => {
    if (!data) return [];
    const out = [];
    const area = (p) => `${p.id}${p.area ? ` ${p.area}` : ''}`;
    const k = (v) => (v >= 1e5 ? `₹${(v / 1e5).toFixed(1)}L` : `₹${(v / 1e3).toFixed(1)}k`);
    for (const r of data.regions.filter((x) => x.projects)) {
      const pins = data.pincodes.filter((p) => p.region_id === r.id && p.projects);
      const priced = pins.filter((p) => p.price_per_sqft).sort((a, b) => b.price_per_sqft.inr - a.price_per_sqft.inr);
      if (priced.length > 1) {
        out.push(`${r.name}: priciest pincode ${area(priced[0])} at ${k(priced[0].price_per_sqft.inr)}/sq ft`);
        out.push(`${r.name}: best value ${area(priced.at(-1))} at ${k(priced.at(-1).price_per_sqft.inr)}/sq ft`);
      }
      const unsold = [...pins].sort((a, b) => b.units_unsold - a.units_unsold)[0];
      if (unsold?.units_unsold) out.push(`${area(unsold)}: ${unsold.units_unsold.toLocaleString('en-IN')} flats still unsold`);
      const busy = [...pins].sort((a, b) => b.under_construction - a.under_construction)[0];
      if (busy?.under_construction) out.push(`${area(busy)}: ${busy.under_construction} projects being built right now`);
    }
    const builder = data.pincodes.flatMap((p) => p.top_builders.map((b) => ({ ...b, pin: p }))).sort((a, b) => b.projects - a.projects)[0];
    if (builder) out.push(`${builder.name}: ${builder.projects} projects in ${area(builder.pin)}`);
    return out;
  });

  onMount(() => {
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    api('/v1/map/insights')
      .then((d) => { data = d; countUp(still); })
      .catch(() => { error = 'The data service did not answer. Start it and reload.'; });
    // The backdrop uses a light sample of positions, not every project.
    api('/v1/map/points')
      .then((sky) => draw(still, sky))
      .catch(() => { error = 'The data service did not answer. Start it and reload.'; });
    if (still) return;
    const turn = setInterval(() => {
      glitching = true;
      setTimeout(() => { word = (word + 1) % WORDS.length; }, GLITCH_MS / 2);
      setTimeout(() => (glitching = false), GLITCH_MS);
    }, 2600);
    return () => { clearInterval(turn); cancelAnimationFrame(frame); };
  });

  function countUp(still) {
    if (still) { counted = 1; return; }
    const start = performance.now();
    const step = (now) => { counted = Math.min(1, (now - start) / 1800); if (counted < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }

  // ---------------------------------------------------------------- the constellation
  let frame = 0;
  function draw(still, sky) {
    const inState = (la, lo) => la > 15 && la < 21 && lo > 72 && lo < 76;
    const pts = sky.points.filter(([la, lo]) => inState(la, lo)).map(([latitude, longitude, late]) => ({ latitude, longitude, late }));
    const named = sky.named.filter((n) => inState(n.lat, n.lng)).map((n) => ({ ...n, latitude: n.lat, longitude: n.lng }));
    if (!canvas || !pts.length) return;
    const ctx = canvas.getContext('2d');
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    let W, H, project;
    const lat = pts.map((p) => p.latitude), lng = pts.map((p) => p.longitude);
    const box = { n: Math.max(...lat), s: Math.min(...lat), e: Math.max(...lng), w: Math.min(...lng) };
    const kx = Math.cos((((box.n + box.s) / 2) * Math.PI) / 180);
    const cities = [{ name: 'MUMBAI', lat: 19.05, lng: 72.86 }, { name: 'THANE', lat: 19.22, lng: 72.98 }, { name: 'PUNE', lat: 18.52, lng: 73.86 }];

    function fit() {
      W = canvas.clientWidth; H = canvas.clientHeight;
      canvas.width = W * dpr; canvas.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const wide = W > 900;
      // weight the points to the right on wide screens, where the text is not
      const area = wide ? { x: W * 0.42, y: H * 0.1, w: W * 0.55, h: H * 0.8 }
        : W > 600 ? { x: W * 0.05, y: H * 0.5, w: W * 0.9, h: H * 0.42 }
        : { x: W * 0.06, y: H - window.innerHeight * 0.34 - 56, w: W * 0.88, h: window.innerHeight * 0.32 }; // phone: its own band under the text
      const sx = area.w / ((box.e - box.w) * kx), sy = area.h / (box.n - box.s);
      const sc = Math.min(sx, sy);
      const ox = area.x + (area.w - (box.e - box.w) * kx * sc) / 2, oy = area.y + (area.h - (box.n - box.s) * sc) / 2;
      project = (la, lo) => [ox + (lo - box.w) * kx * sc, oy + (box.n - la) * sc];
    }
    fit();
    window.addEventListener('resize', fit);

    const placed = pts.map((p) => ({ p, tw: Math.random() * Math.PI * 2, sp: 0.6 + Math.random() * 1.4 }));
    const pulses = [];
    let last = 0;

    const render = (now) => {
      ctx.clearRect(0, 0, W, H);
      for (const c of cities) {
        const [x, y] = project(c.lat, c.lng);
        ctx.font = '600 11px "Red Hat Mono", monospace';
        ctx.fillStyle = 'rgba(244,239,228,0.28)';
        ctx.fillText(c.name, x + 14, y - 12);
      }
      ctx.globalCompositeOperation = 'lighter';
      for (const d of placed) {
        const [x, y] = project(d.p.latitude, d.p.longitude);
        const a = still ? 0.5 : 0.32 + 0.28 * Math.sin(now / 1000 * d.sp + d.tw);
        const late = d.p.late === 1;
        ctx.fillStyle = late ? `rgba(255,107,107,${a})` : `rgba(255,193,61,${a})`;
        ctx.beginPath(); ctx.arc(x, y, 1.3, 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalCompositeOperation = 'source-over';
      if (!still) {
        if (now - last > 650 && named.length) {
          last = now;
          pulses.push({ d: { p: named[Math.floor(Math.random() * named.length)] }, born: now });
          if (pulses.length > 6) pulses.shift();
        }
        for (const pl of pulses) {
          const age = (now - pl.born) / 2400;
          if (age > 1) continue;
          const [x, y] = project(pl.d.p.latitude, pl.d.p.longitude);
          ctx.strokeStyle = `rgba(95,240,173,${0.8 * (1 - age)})`;
          ctx.lineWidth = 1.5;
          ctx.beginPath(); ctx.arc(x, y, 4 + age * 26, 0, Math.PI * 2); ctx.stroke();
          ctx.fillStyle = `rgba(95,240,173,${1 - age})`;
          ctx.beginPath(); ctx.arc(x, y, 2.6, 0, Math.PI * 2); ctx.fill();
          if (age < 0.85 && W > 600) {
            ctx.font = '500 11px "Anek Latin", sans-serif';
            ctx.fillStyle = `rgba(244,239,228,${0.85 * (1 - age)})`;
            ctx.fillText(`${(pl.d.p.name ?? '').slice(0, 24)} · ${pl.d.p.pincode}`, x + 10, y - 8 - age * 10);
          }
        }
        frame = requestAnimationFrame(render);
      }
    };
    frame = requestAnimationFrame(render);
  }
</script>

<section class="hero" aria-labelledby="hero-title">
  <canvas class="hero__sky" bind:this={canvas} aria-hidden="true"></canvas>
  <div class="hero__shade" aria-hidden="true"></div>

  <div class="container hero__body">
    <p class="hero__kicker num"><span class="hero__live"></span>Built on public RERA filings · Pune and Mumbai</p>
    <h1 id="hero-title" class="hero__title">
      <span>Know every</span>
      <span class="hero__word glitch" class:is-glitching={glitching} data-text={WORDS[word]}>{WORDS[word]}</span>
      <span>in your pincode.</span>
    </h1>
    <p class="hero__lead">Leads for the trades, report cards for agents, the real price for buyers. All from public filings, before anyone else reads them.</p>
    <div class="hero__actions">
      <a class="btn btn--primary btn--big" href="#waitlist">Join the waitlist</a>
      <a class="btn btn--big btn--ghost" href="#map">Explore the map</a>
    </div>
    {#if error}<p class="hero__error" role="alert">{error}</p>{/if}

    <dl class="tally">
      <div><dt>Projects tracked</dt><dd class="num">{count(t?.projects).toLocaleString('en-IN')}</dd></div>
      <div><dt>Flats on file</dt><dd class="num">{count(t?.flats).toLocaleString('en-IN')}</dd></div>
      <div><dt>Agreed sales read</dt><dd class="num">₹{crore(t?.agreed_inr)} Cr</dd></div>
      <div><dt>Builders watched</dt><dd class="num">{count(t?.builders).toLocaleString('en-IN')}</dd></div>
    </dl>
  </div>

  {#if facts.length}
    <div class="ticker" aria-label="What the data shows today">
      <div class="ticker__track">
        {#each [...facts, ...facts] as f, i (i)}<span class="ticker__item" aria-hidden={i >= facts.length}>{f}</span>{/each}
      </div>
    </div>
  {/if}
</section>

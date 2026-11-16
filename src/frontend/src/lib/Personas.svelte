<script>
  import { onMount } from 'svelte';

  // Three chapters, played by scrolling: each persona gets its own scene.
  const CHAPTERS = [
    {
      id: 'trades',
      kicker: 'Installers, suppliers, contractors',
      title: 'See the building before your competitor does.',
      body: 'We watch satellite imagery and RERA filings for new buildings rising in your area, and tell you the moment each one reaches the stage where it needs you. Send your sales rep in with an irresistible offer and close a warm lead, not a cold call.',
      points: ['Only the pincodes you serve', 'Timed to the construction stage you sell into', 'Builder name, flat count, possession date'],
    },
    {
      id: 'agents',
      kicker: 'Real estate agents',
      title: 'Walk in with the report. Walk out with the client.',
      body: 'A clear picture of every pincode: which projects are selling fast, which are stuck, the real price points, and what is driving growth, quarter by quarter.',
      points: ['Project scorecards: good, slow, risky', 'Price and absorption time series', 'Growth drivers per pincode'],
    },
    {
      id: 'buyers',
      kicker: 'Home buyers',
      title: 'The salesperson called. Here is what others actually paid.',
      body: 'The lowest price buyers really agreed in that project, from its own filings, next to how many flats are sold, the complaints lodged and the court cases open.',
      points: ['Real agreed prices, flat by flat', 'Sold, booked and unsold, honestly', 'Complaints and court cases before you sign'],
    },
  ];
  const TRADES = [
    { who: 'Elevator installer', lead: '2 towers, G+22, Wakad 411057', when: 'Structure at 60%. Lift orders go out next.' },
    { who: 'Solar installer', lead: '4,800 sq ft of roof, Baner 411045', when: 'Terrace slab done. Possession Mar 2027.' },
    { who: 'Sanitaryware supplier', lead: '312 flats, Hadapsar 411028', when: 'Fit-out starts in 3 months.' },
    { who: 'Painter', lead: '3 projects at plaster stage, 411033', when: 'Painting contracts in 6 to 8 weeks.' },
  ];
  // Footprints that "appear" on the satellite tile, in the order they are found.
  const BUILDINGS = [
    { x: 10, y: 20, w: 13, h: 9 }, { x: 40, y: 12, w: 9, h: 14 }, { x: 22, y: 64, w: 12, h: 10 },
    { x: 8, y: 44, w: 8, h: 12 }, { x: 28, y: 38, w: 9, h: 9 }, { x: 56, y: 10, w: 8, h: 11 },
  ];
  const SERIES = [16900, 17400, 18300, 18900, 19800, 20700, 21600, 22850]; // Balewadi-like price per sq ft, 8 quarters
  const BOARD = [
    { name: 'Project A', tag: 'Moving fast', sold: 82, tone: 'good' },
    { name: 'Project B', tag: 'Steady', sold: 54, tone: 'mid' },
    { name: 'Project C', tag: 'Stalled, 14 months late', sold: 21, tone: 'bad' },
  ];
  const QUOTE = 11200000; // what the salesperson says is final
  const LOWEST = 9080350; // lowest agreed in the filings: Hadapsar 411028, 500 to 1,000 sq ft

  let section = $state();
  let progress = $state(0);
  let still = $state(false);

  const chapter = $derived(Math.min(CHAPTERS.length - 1, Math.floor(progress * CHAPTERS.length)));
  const local = $derived(still ? 1 : Math.min(1, (progress * CHAPTERS.length - chapter) * 1.25));
  const ease = (t) => 1 - (1 - t) ** 3;
  const step = (t, from, to) => Math.min(1, Math.max(0, (t - from) / (to - from)));

  const trade = $derived(Math.min(TRADES.length - 1, Math.floor(step(local, 0.35, 1) * TRADES.length)));
  const shown = $derived(chapter === 2 ? QUOTE - (QUOTE - LOWEST) * ease(step(local, 0.25, 0.75)) : QUOTE);
  const lakh = (v) => (v >= 1e7 ? `₹${(v / 1e7).toFixed(2)} Cr` : `₹${(v / 1e5).toFixed(1)} L`);
  const lo = Math.min(...SERIES), hi = Math.max(...SERIES);
  const path = SERIES.map((v, i) => `${i ? 'L' : 'M'}${(i * 300) / (SERIES.length - 1)},${110 - ((v - lo) / (hi - lo)) * 96}`).join('');

  onMount(() => {
    still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let ticking = false;
    const track = () => {
      ticking = false;
      if (!section) return;
      const box = section.getBoundingClientRect();
      const run = box.height - window.innerHeight;
      progress = run > 0 ? Math.min(0.9999, Math.max(0, -box.top / run)) : 0;
    };
    const onScroll = () => { if (!ticking) { ticking = true; requestAnimationFrame(track); } };
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    track();
    return () => { window.removeEventListener('scroll', onScroll); window.removeEventListener('resize', onScroll); };
  });
</script>

<section class="story" bind:this={section} id="who" aria-label="How Subak helps you">
  <div class="story__stage container">
    <div class="story__copy">
      <ol class="story__tabs" aria-label="Chapters">
        {#each CHAPTERS as c, i (c.id)}
          <li class:is-on={chapter === i} class:is-done={chapter > i}><span class="num">0{i + 1}</span>{c.kicker}</li>
        {/each}
      </ol>
      {#key chapter}
        <div class="story__text">
          <h2>{CHAPTERS[chapter].title}</h2>
          <p>{CHAPTERS[chapter].body}</p>
          <ul class="story__points">
            {#each CHAPTERS[chapter].points as pt (pt)}<li>{pt}</li>{/each}
          </ul>
        </div>
      {/key}
    </div>

    <div class="story__scene" aria-hidden="true">
      {#if chapter === 0}
        <div class="sat">
          <div class="sat__ground"></div>
          <div class="sat__scan" style:top="{step(local, 0, 0.6) * 100}%"></div>
          {#each BUILDINGS as b, i (i)}
            <span class="sat__bld" class:is-on={local > 0.08 + i * 0.08}
                  style:left="{b.x}%" style:top="{b.y}%" style:width="{b.w}%" style:height="{b.h}%">
              <i>NEW</i>
            </span>
          {/each}
          <p class="sat__meta num">SCAN · PUNE WEST · {Math.round(step(local, 0, 0.6) * 100)}%</p>
          <div class="sat__leads">
            {#each TRADES as t, i (t.who)}
              <div class="lead" class:is-on={local > 0.35 + i * 0.12} class:is-pick={trade === i && local > 0.35}>
                <p class="lead__who">{t.who}</p>
                <p class="lead__what">{t.lead}</p>
                <p class="lead__when">{t.when}</p>
              </div>
            {/each}
          </div>
        </div>
      {:else if chapter === 1}
        <div class="report">
          <header class="report__head">
            <p class="report__kind">Pincode report</p>
            <h3>411045 · Balewadi</h3>
            <p class="report__price num">₹{SERIES.at(-1).toLocaleString('en-IN')}<small>/sq ft</small><span class="delta delta--up">+35% in 2 yrs</span></p>
          </header>
          <svg class="report__chart" viewBox="0 0 300 120" preserveAspectRatio="none">
            <defs><linearGradient id="rp" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="currentColor" stop-opacity=".35" /><stop offset="1" stop-color="currentColor" stop-opacity="0" /></linearGradient></defs>
            <path d="{path}L300,120L0,120Z" fill="url(#rp)" style:opacity={step(local, 0.1, 0.5)} />
            <path d={path} class="report__line" pathLength="1" style:stroke-dashoffset={1 - step(local, 0.05, 0.5)} />
          </svg>
          <div class="report__board">
            {#each BOARD as r, i (r.name)}
              <div class="row row--{r.tone}" class:is-on={local > 0.4 + i * 0.1}>
                <span class="row__name">{r.name}</span>
                <span class="row__bar"><i style:width="{r.sold * step(local, 0.4 + i * 0.1, 0.7 + i * 0.1)}%"></i></span>
                <span class="row__tag">{r.tag}</span>
              </div>
            {/each}
          </div>
          <ul class="report__drivers" class:is-on={local > 0.75}>
            <li>Metro line 3 station, 1.2 km</li><li>2 IT parks hiring</li><li>9 launches this year</li>
          </ul>
        </div>
      {:else}
        <div class="callphone">
          <div class="call" class:is-on={local > 0.02}>
            <p class="call__who">Sales executive · calling</p>
            <p class="call__said">“₹1.12 Cr is final. We never go lower than that.”</p>
          </div>
          <div class="truth" class:is-on={local > 0.2}>
            <p class="truth__label">Lowest price agreed for the same size here</p>
            <p class="truth__big num">{lakh(shown)}</p>
            <p class="truth__gap num" class:is-on={local > 0.75}>{lakh(QUOTE - LOWEST)} below the “final” price</p>
            <p class="truth__src">138 sold flats of 500 to 1,000 sq ft, Hadapsar 411028, from RERA filings</p>
          </div>
          <dl class="rep" class:is-on={local > 0.6}>
            <div><dt>Flats sold</dt><dd class="num">62%</dd></div>
            <div><dt>Complaints</dt><dd class="num bad">3</dd></div>
            <div><dt>Court cases</dt><dd class="num bad">1</dd></div>
          </dl>
        </div>
      {/if}
      <p class="story__caption">{chapter === 2 ? 'Prices are real filings; the call and reputation figures are an example.' : 'Example of what a member sees.'}</p>
    </div>
  </div>
</section>

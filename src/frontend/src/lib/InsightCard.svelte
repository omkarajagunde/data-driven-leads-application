<script>
  import { num, money, date, SCHEDULE } from './format.js';
  import Spark from './Spark.svelte';

  // record: { kind: 'region' | 'zone' | 'pincode' | 'project', data, context }
  // Each level shows the figures that matter at that height: market size up top,
  // supply and prices in the middle, trust signals for a single project.
  // sizes: the flat types the map is filtered to. peek: one line for the phone's collapsed sheet.
  let { record, quarters = [], currency = 'inr', compact = false, peek = false, sizes = ['1', '2', '3', '4'] } = $props();

  const d = $derived(record?.data);
  const kind = $derived(record?.kind);
  const t = $derived(d?.trend);
  const signed = (v) => (v == null ? 'n/a' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}%`);
  const tone = (v) => (v == null ? '' : v > 0 ? 'up' : v < 0 ? 'down' : '');
  const pricePts = $derived(t?.price_per_sqft?.map((v) => (currency === 'usd' ? v / (d.price_per_sqft?.inr / d.price_per_sqft?.usd || 88) : v)));
  const fmtPrice = (v) => money({ inr: v, usd: v }, currency);
  const sold = $derived(d?.units_total ? Math.round(((d.units_total - d.units_unsold) * 100) / d.units_total) : null);
  const late = $derived(['late', 'overdue'].includes(d?.schedule));
  const vsArea = $derived(
    kind === 'project' && d?.price_per_sqft && record.context?.price_per_sqft
      ? ((d.price_per_sqft.inr - record.context.price_per_sqft.inr) * 100) / record.context.price_per_sqft.inr
      : null,
  );
  const KIND = { region: 'Region', zone: 'Zone', pincode: 'Pincode', project: 'Project' };
  const BHK_NAME = { 1: '1 BHK', 2: '2 BHK', 3: '3 BHK', 4: '4+ BHK' };
  // [flats, unsold, priced, price sum, projects] per size, in display order, with each size's share of flats
  const bhk = $derived.by(() => {
    const b = d?.bhk ?? {};
    const rows = ['1', '2', '3', '4'].map((k) => ({ k, flats: b[k]?.[0] ?? 0, unsold: b[k]?.[1] ?? 0, ppsf: b[k]?.[2] ? b[k][3] / b[k][2] : null }));
    const all = rows.reduce((n, r) => n + r.flats, 0);
    return all ? rows.map((r) => ({ ...r, share: (r.flats * 100) / all })) : [];
  });
  const bhkMax = $derived(Math.max(1, ...bhk.map((r) => r.share)));
  const inr = (v) => money({ inr: v, usd: v / (d?.price_per_sqft?.inr / d?.price_per_sqft?.usd || 88) }, currency, { compact: true });
  const filterNote = $derived(sizes.length < 4 ? sizes.map((k) => BHK_NAME[k]).join(', ') : '');
  const rera = $derived(kind === 'project' && d?.url ? { href: d.url, label: `Open on ${d.authority ?? 'RERA'}` } : null);
</script>

{#if record && d && peek}
  <!-- the collapsed sheet on a phone: what it is, and the one number that matters -->
  <article class="insight insight--peek">
    <p class="insight__kind"><span class="insight__level">{KIND[kind]}</span><span>{filterNote || record.sub || ''}</span></p>
    <div class="peek">
      <h3 class="insight__title">{record.title}</h3>
      <p class="peek__big num">{d.price_per_sqft ? money(d.price_per_sqft, currency, { compact: true }) : num(kind === 'project' ? d.units_total : d.projects)}<small>{d.price_per_sqft ? '/sq ft' : kind === 'project' ? ' flats' : ' projects'}</small></p>
    </div>
    <p class="peek__facts num">
      {#if kind === 'project'}
        <span class="pill" class:pill--bad={late}>{SCHEDULE[d.schedule] ?? 'Unknown'}</span>
        {#if d.built_pct != null}<span>{Math.round(d.built_pct)}% built</span>{/if}
        {#if d.court_cases}<span class="bad">{d.court_cases} court {d.court_cases === 1 ? 'case' : 'cases'}</span>{/if}
        {#if rera}<a class="peek__link" href={rera.href} target="_blank" rel="noopener noreferrer">RERA<span aria-hidden="true"> ↗</span><span class="visually-hidden"> filing, opens in a new tab</span></a>{/if}
      {:else}
        <span>{num(d.projects)} projects</span><span>{num(d.units_unsold)} unsold</span>
        {#if t?.price_qoq_pct != null}<span class="delta delta--{tone(t.price_qoq_pct)} delta--mini">{signed(t.price_qoq_pct)} QoQ</span>{/if}
      {/if}
    </p>
  </article>
{:else if record && d}
  <article class="insight insight--{kind}" class:is-compact={compact}>
    <header class="insight__head">
      <p class="insight__kind"><span class="insight__level">{KIND[kind]}</span><span>{record.sub ?? ''}</span></p>
      <h3 class="insight__title">{record.title}</h3>
      {#if filterNote}<p class="insight__filter">Showing {filterNote} only</p>{/if}
    </header>

    {#if kind === 'project'}
      <div class="insight__hero">
        <p class="insight__big num">{d.price_per_sqft ? money(d.price_per_sqft, currency) : num(d.units_total)}<small>{d.price_per_sqft ? '/sq ft' : ' units'}</small></p>
        {#if vsArea != null}
          <span class="delta delta--{vsArea > 0 ? 'down' : 'up'}" title="Against the pincode average">{signed(vsArea)} vs area</span>
        {/if}
      </div>
      <dl class="stats">
        <div><dt>Schedule</dt><dd><span class="pill" class:pill--bad={late}>{SCHEDULE[d.schedule] ?? 'Unknown'}</span></dd></div>
        <div><dt>Possession</dt><dd class="num">{date(d.possession)}</dd></div>
        <div><dt>Complaints</dt><dd class="num" class:bad={d.complaints > 0}>{num(d.complaints ?? 0)}</dd></div>
        <div><dt>Court cases</dt><dd class="num" class:bad={d.court_cases > 0}>{num(d.court_cases ?? 0)}</dd></div>
      </dl>
      {#if d.built_pct != null}
        <div class="meter"><span>Built</span><div class="meter__bar"><i style:width="{d.built_pct}%"></i></div><b class="num">{Math.round(d.built_pct)}%</b></div>
      {/if}
      {#if d.units_total}
        <div class="meter"><span>Sold</span><div class="meter__bar meter__bar--sold"><i style:width="{((d.units_sold ?? 0) * 100) / d.units_total}%"></i></div><b class="num">{num(d.units_sold ?? 0)}/{num(d.units_total)}</b></div>
      {/if}
      {#if bhk.length && !compact}
        <ul class="bhkmix" aria-label="Flats by type, estimated from carpet area">
          {#each bhk.filter((r) => r.flats) as r (r.k)}
            <li class:is-off={!sizes.includes(r.k)}><b>{BHK_NAME[r.k]}</b><span class="num">{num(r.flats)}</span>{#if r.ppsf}<span class="num">{inr(r.ppsf)}/sq ft</span>{/if}</li>
          {/each}
        </ul>
      {/if}
      {#if d.builder}<p class="insight__foot">By {d.builder}</p>{/if}
      {#if rera}<a class="insight__link" href={rera.href} target="_blank" rel="noopener noreferrer">{rera.label}<span aria-hidden="true"> ↗</span><span class="visually-hidden"> (opens in a new tab)</span></a>{/if}
    {:else}
      <div class="insight__hero">
        <p class="insight__big num">{d.price_per_sqft ? money(d.price_per_sqft, currency) : num(d.projects)}<small>{d.price_per_sqft ? '/sq ft' : ' projects'}</small></p>
        {#if t?.price_qoq_pct != null}<span class="delta delta--{tone(t.price_qoq_pct)}">{signed(t.price_qoq_pct)} QoQ</span>{/if}
        {#if t?.price_yoy_pct != null && !compact}<span class="delta delta--{tone(t.price_yoy_pct)}">{signed(t.price_yoy_pct)} YoY</span>{/if}
      </div>

      {#if pricePts && !compact}
        <Spark values={pricePts} labels={quarters} format={fmtPrice} />
      {/if}

      <dl class="stats">
        <div><dt>Projects</dt><dd class="num">{num(d.projects)}</dd></div>
        <div>
          <dt>Launches this qtr</dt>
          <dd class="num">{num(t?.launches?.at(-1))} {#if t?.launches_qoq_pct != null}<span class="delta delta--{tone(t.launches_qoq_pct)} delta--mini">{signed(t.launches_qoq_pct)}</span>{/if}</dd>
        </div>
        {#if kind === 'pincode'}
          <div><dt>Being built</dt><dd class="num">{num(d.under_construction)}</dd></div>
          <div><dt>Unsold flats</dt><dd class="num">{num(d.units_unsold)}</dd></div>
        {:else}
          <div><dt>Flats offered</dt><dd class="num">{num(d.units_total)}</dd></div>
          <div><dt>Sold so far</dt><dd class="num">{sold == null ? 'n/a' : `${sold}%`}</dd></div>
        {/if}
      </dl>

      {#if !compact}
        {#if kind === 'region' && d.zones_by_price?.length}
          <div class="ranks">
            <p class="ranks__title">Zones by price</p>
            {#each d.zones_by_price.slice(0, 4) as z (z.name)}
              <div class="ranks__row">
                <span>{z.name}</span>
                <i style:width="{(z.price_per_sqft.inr * 100) / d.zones_by_price[0].price_per_sqft.inr}%"></i>
                <b class="num">{money(z.price_per_sqft, currency, { compact: true })}</b>
              </div>
            {/each}
          </div>
        {:else if kind === 'zone' && d.hot_pincodes?.length}
          <div class="ranks">
            <p class="ranks__title">Most launches this quarter</p>
            {#each d.hot_pincodes as p (p.pincode)}
              <div class="ranks__row ranks__row--plain">
                <span><b class="num">{p.pincode}</b> {p.area ?? ''}</span>
                <b class="num">{p.launches} new</b>
              </div>
            {/each}
          </div>
        {/if}
        {#if kind !== 'region' && bhk.length}
          <div class="ranks">
            <p class="ranks__title">Flats by type <span>· est. from carpet area</span></p>
            {#each bhk as r (r.k)}
              <div class="ranks__row ranks__row--bhk" class:is-off={!sizes.includes(r.k)}>
                <span>{BHK_NAME[r.k]}</span>
                <i style:width="{(r.share * 100) / bhkMax}%"></i>
                <b class="num">{Math.round(r.share)}%{#if r.ppsf} · {inr(r.ppsf)}{/if}</b>
              </div>
            {/each}
          </div>
        {/if}
        {#if kind === 'pincode'}
          {#if d.top_builders?.length}
            <p class="insight__foot">Top builders: {d.top_builders.map((b) => b.name).join(' · ')}</p>
          {/if}
        {/if}
        {#if t?.sample}<p class="insight__sample">Quarterly trend is sample data until filing history builds up.</p>{/if}
      {/if}
    {/if}
  </article>
{/if}

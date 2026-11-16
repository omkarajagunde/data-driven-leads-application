<script>
  // A tiny trend chart: a line with a soft area under it, or bars. Last point is marked.
  let { values = [], labels = [], kind = 'line', format = (v) => v } = $props();

  const W = 220, H = 52, PAD = 4;
  const clean = $derived(values.filter((v) => v != null));
  const lo = $derived(kind === 'bars' ? 0 : Math.min(...clean));
  const hi = $derived(Math.max(...clean, lo + 1));
  const x = (i) => PAD + (i * (W - PAD * 2)) / Math.max(1, values.length - 1);
  const y = (v) => H - PAD - ((v - lo) / (hi - lo)) * (H - PAD * 2);
  const line = $derived(values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(''));
  const area = $derived(`${line}L${x(values.length - 1)},${H}L${x(0)},${H}Z`);
  const bw = $derived((W - PAD * 2) / Math.max(1, values.length) - 3);
  const id = `g${Math.random().toString(36).slice(2, 8)}`;
</script>

{#if clean.length > 1}
  <figure class="spark">
    <svg viewBox="0 0 {W} {H}" preserveAspectRatio="none" role="img" aria-label="Trend over {values.length} quarters">
      {#if kind === 'bars'}
        {#each values as v, i (i)}
          <rect class:is-last={i === values.length - 1} x={PAD + i * (bw + 3)} y={y(v)} width={bw} height={Math.max(1.5, H - PAD - y(v))} rx="2">
            <title>{labels[i]}: {format(v)}</title>
          </rect>
        {/each}
      {:else}
        <defs>
          <linearGradient {id} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stop-color="currentColor" stop-opacity="0.35" />
            <stop offset="1" stop-color="currentColor" stop-opacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill="url(#{id})" />
        <path d={line} class="spark__line" />
        <circle cx={x(values.length - 1)} cy={y(values[values.length - 1])} r="3.5" class="spark__dot" />
      {/if}
    </svg>
    <figcaption><span>{labels[0]}</span><span>{labels[labels.length - 1]}</span></figcaption>
  </figure>
{/if}

<script>
  import { onMount } from 'svelte';
  import { api, DOCS_URL } from './lib/api.js';
  import Splash from './lib/Splash.svelte';
  import Hero from './lib/Hero.svelte';
  import MapQuest from './lib/MapQuest.svelte';
  import Waitlist from './lib/Waitlist.svelte';
  import Personas from './lib/Personas.svelte';
  import Pricing from './lib/Pricing.svelte';

  let regions = $state([]);

  const AUDIENCES = [
    {
      ask: 'Buying a new house or flat?',
      answer: 'Check real rates, project status, complaints and court cases. Compare projects on facts, not on a salesperson’s word.',
    },
    { ask: 'Real estate agent?', answer: 'Close more clients with competitive intel on every project around you.' },
    { ask: 'Material supplier?', answer: 'Get leads in the exact area you serve, from projects that are being built now.' },
    { ask: 'Architect or interior designer?', answer: 'Find projects nearing possession, where your next clients are.' },
  ];

  const reraSites = $derived(
    [...new Map(regions.filter((r) => r.rera.website).map((r) => [r.rera.authority, r.rera.website])).entries()],
  );

  onMount(() => {
    api('/v1/regions').then((r) => (regions = r)).catch(() => {});
  });
</script>

<Splash />

<a class="skip" href="#map">Skip to the map</a>

<header class="nav">
  <nav class="nav__pill" aria-label="Main">
    <a class="nav__mark" href="#top" aria-label="Subak Market Intelligence"><span class="nav__dot" aria-hidden="true"></span>Subak<span class="nav__tag">Market Intelligence</span></a>
    <a class="nav__link" href="#map">The map</a>
    <a class="nav__link" href="#pricing">Pricing</a>
    <a class="btn btn--primary btn--small" href="#waitlist">Join the waitlist</a>
  </nav>
</header>

<main id="top">
  <Hero />

  <section class="aud" aria-label="Who it is for">
    <div class="container">
      <ul class="aud__list">
        {#each AUDIENCES as a, i (a.ask)}
          <li class="aud__card" style:--i={i}>
            <p class="aud__ask">{a.ask}</p>
            <p class="aud__answer">{a.answer}</p>
          </li>
        {/each}
      </ul>
      <p class="aud__then">Then use <b>Subak</b>.</p>
    </div>
  </section>

  <div class="bridge" aria-hidden="true"></div>

  <MapQuest {regions} />

  <Personas />

  <Pricing />

  <Waitlist />
</main>

<footer class="foot">
  <div class="container">
    <p class="foot__statement"><span>SUBAK</span> Every figure traces back to a public RERA filing.</p>
    <nav class="foot__links" aria-label="Footer">
      <a href="#map">The map</a>
      <a href="#waitlist">Join the waitlist</a>
      <a href={DOCS_URL}>API docs</a>
      {#each reraSites as [authority, site] (authority)}
        <a href={site} rel="noreferrer">{authority}</a>
      {/each}
    </nav>
  </div>
</footer>

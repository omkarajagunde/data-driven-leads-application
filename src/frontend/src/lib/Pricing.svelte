<script>
  // What each persona pays with us, against what they pay today. Figures for others are public list
  // prices or published ranges; where a company does not publish prices we say so instead of guessing.
  const PLANS = [
    {
      who: 'Installers, suppliers, contractors',
      name: 'Leads',
      tiers: [
        { name: 'Starter', price: '₹5,000', per: 'a month', leads: 10 },
        { name: 'Growth', price: '₹15,000', per: 'a month', leads: 25 },
      ],
      ours: ['New buildings in the pincodes you choose', 'Alerts at the construction stage you sell into', 'Builder, flat count and possession date per lead'],
      them: 'Lead marketplaces and listing sites',
      cost: '₹1 lakh+ a year',
      note: 'Spread across several platforms. IndiaMART’s entry seller plan alone is about ₹35,000 to ₹40,000 a year plus GST, before visibility add-ons, and the same buyer enquiry goes to many sellers.',
    },
    {
      who: 'Real estate agents',
      name: 'Agent Pro',
      price: '₹5,000',
      per: 'a month',
      quota: '10 pincode reports + 5 zone reports every month',
      ours: ['Tracking: alerts when prices, launches or a project’s status change in your areas', 'Price, launches and absorption time series', 'AI insights you can share with clients'],
      them: 'Institutional data platforms and consultants',
      cost: 'Priced on request',
      note: 'Annual contracts built for developers, lenders and funds. Public rate cards are not published.',
      featured: true,
    },
    {
      who: 'Home buyers',
      name: 'Report',
      price: '₹2,500',
      per: 'per report',
      ours: ['Project, pincode or zone report', 'Lowest real agreed prices for your flat size', 'Complaints, court cases, delays, plus AI insights'],
      them: 'A broker’s word, or a lawyer’s title check',
      cost: 'Free, or ₹8,000 to ₹30,000',
      note: 'A broker is paid by the builder. A lawyer checks the papers, not the price. Use us for price and reputation, and a lawyer for title.',
    },
  ];
  let tier = $state(0);
</script>

<section class="pricing" id="pricing" aria-labelledby="pricing-title">
  <div class="container">
    <header class="pricing__head">
      <p class="pricing__kicker">Pricing</p>
      <h2 id="pricing-title">Consultant-grade insight, at a local business price.</h2>
    </header>
    <div class="plans">
      {#each PLANS as p (p.name)}
        <article class="plan" class:plan--featured={p.featured}>
          <p class="plan__who">{p.who}</p>
          <h3 class="plan__name">{p.name}</h3>
          {#if p.tiers}
            <div class="plan__tiers" role="group" aria-label="Leads plan size">
              {#each p.tiers as t, i (t.name)}
                <button type="button" class:is-on={tier === i} aria-pressed={tier === i} onclick={() => (tier = i)}>{t.name}</button>
              {/each}
            </div>
            <p class="plan__price"><span class="num">{p.tiers[tier].price}</span> <small>{p.tiers[tier].per} + GST</small></p>
            <p class="plan__quota">At least <b class="num">{p.tiers[tier].leads}</b> leads a month</p>
          {:else}
            <p class="plan__price"><span class="num">{p.price}</span> <small>{p.per} + GST</small></p>
            {#if p.quota}<p class="plan__quota">{p.quota}</p>{/if}
          {/if}
          <ul class="plan__ours">{#each p.ours as o (o)}<li>{o}</li>{/each}</ul>
          <div class="plan__vs">
            <p class="plan__them">Instead of: {p.them}</p>
            <p class="plan__cost num">{p.cost}</p>
            <p class="plan__note">{p.note}</p>
          </div>
          <a class="btn {p.featured ? 'btn--primary' : ''}" href="#waitlist">Get early access</a>
        </article>
      {/each}
    </div>
    <p class="pricing__foot">Launch prices for waitlist members. Other companies’ prices are public list prices or published ranges as of November 2026.</p>
  </div>
</section>

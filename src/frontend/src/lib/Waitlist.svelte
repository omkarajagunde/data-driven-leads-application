<script>
  import { post } from './api.js';

  const PROFESSIONS = [
    'Home buyer', 'Real estate agent', 'Builder or developer', 'Material supplier', 'Contractor',
    'Construction services', 'Architect', 'Interior designer', 'Home loan or finance', 'Other',
  ];
  // Construction businesses also say what they sell, so leads can be matched to them.
  const BUSINESSES = ['Material supplier', 'Contractor', 'Construction services'];
  const CATEGORIES = [
    'Cement and concrete', 'Steel and TMT', 'Bricks and blocks', 'Sand and aggregates', 'Tiles and flooring',
    'Sanitaryware and plumbing', 'Electricals and lighting', 'Paint and waterproofing', 'Doors, windows and glass',
    'Modular kitchen and furniture', 'Lifts and elevators', 'Solar and power backup', 'Security and automation', 'Other',
  ];

  let name = $state('');
  let profession = $state('');
  let categories = $state([]);
  let whatsapp = $state('');
  let sending = $state(false);
  let error = $state('');
  let done = $state('');

  const isBusiness = $derived(BUSINESSES.includes(profession));
  const digits = $derived(whatsapp.replace(/\D/g, '').replace(/^(91|0)(?=\d{10}$)/, ''));

  async function submit(e) {
    e.preventDefault();
    error = '';
    if (name.trim().length < 2) return (error = 'Tell us your name.');
    if (!profession) return (error = 'Pick what you do.');
    if (isBusiness && !categories.length) return (error = 'Pick at least one business category.');
    if (!/^[6-9]\d{9}$/.test(digits)) return (error = 'Enter a 10-digit WhatsApp number.');
    sending = true;
    try {
      const res = await post('/v1/waitlist', {
        name: name.trim(), profession, categories: isBusiness ? categories : [], whatsapp: digits,
      });
      done = res.status === 'updated' ? 'updated' : 'joined';
    } catch (err) {
      error = err.message || 'That did not go through. Please try again.';
    } finally {
      sending = false;
    }
  }
</script>

<section class="waitlist" id="waitlist">
  <div class="container waitlist__grid">
    <div class="waitlist__head">
      <h2>Want more leads? Join the waitlist.</h2>
      <p>Tell us what you do. We message you on WhatsApp when your area opens.</p>
    </div>

    {#if done}
      <div class="waitlist__done" role="status">
        <h3>{done === 'updated' ? 'Your details are updated' : 'You are on the list'}, {name.trim().split(' ')[0]}.</h3>
        <p>We will message +91 {digits} when Subak opens for {profession.toLowerCase()}s.</p>
      </div>
    {:else}
      <form class="form" onsubmit={submit} novalidate>
        <div class="field">
          <label for="wl-name">Your name</label>
          <input id="wl-name" type="text" autocomplete="name" maxlength="80" bind:value={name} required />
        </div>

        <fieldset class="field">
          <legend>What do you do?</legend>
          <div class="picks">
            {#each PROFESSIONS as p (p)}
              <label class="pick">
                <input type="radio" name="profession" value={p} bind:group={profession} />
                <span>{p}</span>
              </label>
            {/each}
          </div>
        </fieldset>

        {#if isBusiness}
          <fieldset class="field field--rise">
            <legend>What does your business sell?</legend>
            <div class="picks">
              {#each CATEGORIES as c (c)}
                <label class="pick">
                  <input type="checkbox" value={c} bind:group={categories} />
                  <span>{c}</span>
                </label>
              {/each}
            </div>
          </fieldset>
        {/if}

        <div class="field">
          <label for="wl-phone">WhatsApp number</label>
          <div class="phone">
            <span class="phone__code num">+91</span>
            <input id="wl-phone" class="num" type="tel" inputmode="numeric" autocomplete="tel-national" maxlength="14" bind:value={whatsapp} required />
          </div>
        </div>

        {#if error}<p class="form__error" role="alert">{error}</p>{/if}

        <button type="submit" class="btn btn--ink" disabled={sending}>{sending ? 'Joining' : 'Join the waitlist'}</button>
        <p class="form__note">We use your number only to tell you about Subak.</p>
      </form>
    {/if}
  </div>
</section>

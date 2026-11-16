<script>
  import { onMount } from 'svelte';

  let { ondone } = $props();

  const LETTERS = ['S', 'U', 'B', 'A', 'K'];
  const ALL = [0, 1, 2, 3, 4];
  // The name arrives in pieces: S, then BA, then K, then the whole word.
  const BEATS = [[520, [2, 3]], [1040, [4]], [1560, ALL]];

  let lit = $state([0]);
  let settled = $state(false);
  let leaving = $state(false);
  let gone = $state(false);
  let timers = [];

  function close() {
    if (leaving) return;
    leaving = true;
    timers.push(setTimeout(() => {
      gone = true;
      document.documentElement.classList.remove('is-splash');
      ondone?.();
    }, 460));
  }

  onMount(() => {
    document.documentElement.classList.add('is-splash');
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (still) {
      lit = ALL;
      settled = true;
      timers.push(setTimeout(close, 1100));
    } else {
      for (const [at, set] of BEATS) timers.push(setTimeout(() => (lit = set), at));
      timers.push(setTimeout(() => (settled = true), 2150));
      timers.push(setTimeout(close, 3200));
    }
    const onKey = (e) => (e.key === 'Escape' || e.key === 'Enter' || e.key === ' ') && close();
    window.addEventListener('keydown', onKey);
    return () => {
      timers.forEach(clearTimeout);
      window.removeEventListener('keydown', onKey);
      document.documentElement.classList.remove('is-splash');
    };
  });
</script>

{#if !gone}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="splash" class:is-leaving={leaving} onclick={close}>
    <p class="splash__word" class:is-settled={settled} aria-label="Subak">
      {#each LETTERS as letter, i (letter)}<span class="glitch" class:is-off={!lit.includes(i)} data-text={letter} aria-hidden="true">{letter}</span>{/each}
    </p>
    <p class="splash__sub">Business Intelligence Network</p>
    <button type="button" class="splash__skip" onclick={close}>Skip</button>
  </div>
{/if}

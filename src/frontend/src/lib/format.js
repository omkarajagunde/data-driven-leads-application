const whole = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
const wholeUs = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });

export const num = (v) => (v === null || v === undefined ? 'n/a' : whole.format(v));

export const pct = (v) => (v === null || v === undefined ? 'n/a' : `${Number(v).toFixed(1)}%`);

/** A money object from the API ({inr, usd}) as a short string in the chosen currency. */
export function money(m, currency = 'inr', { compact = false } = {}) {
  if (!m) return 'n/a';
  if (currency === 'usd') {
    const v = m.usd;
    if (compact && v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
    if (compact && v >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
    return `$${wholeUs.format(v)}`;
  }
  const v = m.inr;
  if (compact && v >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
  if (compact && v >= 1e5) return `₹${(v / 1e5).toFixed(1)} L`;
  return `₹${whole.format(v)}`;
}

export const date = (v) =>
  v ? new Date(v).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : 'n/a';

export const SCHEDULE = {
  on_time: 'On time',
  late: 'Late',
  overdue: 'Overdue',
  early: 'Ahead of time',
  completed: 'Completed',
};

export const KIND = { region: 'Region', zone: 'Zone', pincode: 'Pincode', project: 'Project' };

const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });

export function timeAgo(iso) {
  if (!iso) return '';
  const seconds = (new Date(iso).getTime() - Date.now()) / 1000;
  const units = [
    ['year', 31536000], ['month', 2592000], ['week', 604800],
    ['day', 86400], ['hour', 3600], ['minute', 60],
  ];
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit);
  }
  return 'just now';
}

export function formatDateTime(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

// Formats a YYYY-MM-DD string; anything else is returned as-is.
export function formatDocDate(value) {
  if (!value) return '';
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const [y, m, d] = value.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' });
}

export function formatMoney(amount, currency) {
  if (amount == null || amount === '') return '';
  const n = Number(amount);
  if (Number.isNaN(n)) return String(amount);
  const formatted = n.toLocaleString(undefined, { minimumFractionDigits: n % 1 ? 2 : 0, maximumFractionDigits: 2 });
  return currency ? `${currency} ${formatted}` : formatted;
}

export function compactNumber(n) {
  return Number(n).toLocaleString(undefined, { notation: 'compact', maximumFractionDigits: 1 });
}

export function percent(value) {
  return value == null ? '—' : `${Math.round(value * 100)}%`;
}

export function fileKind(filename = '') {
  const ext = filename.split('.').pop().toLowerCase();
  if (ext === 'pdf') return 'PDF';
  if (['png', 'jpg', 'jpeg'].includes(ext)) return ext === 'png' ? 'PNG' : 'JPG';
  if (['tif', 'tiff'].includes(ext)) return 'TIFF';
  return ext.toUpperCase() || 'FILE';
}

export function greeting(date = new Date()) {
  const h = date.getHours();
  if (h < 5) return 'Working late';
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}

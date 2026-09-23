// A document's status as the user thinks about it:
// processing -> failed | needs review (low-confidence values) | ready
export const STATUS = {
  processing: { label: 'Processing', tone: 'info', processing: true },
  error: { label: 'Failed', tone: 'bad' },
  review: { label: 'Needs review', tone: 'warn' },
  ready: { label: 'Ready', tone: 'ok' },
};

export function displayStatus(doc) {
  if (!doc) return 'processing';
  if (doc.status === 'processing') return 'processing';
  if (doc.status === 'error') return 'error';
  if (!doc.edited && doc.summary?.low_confidence > 0) return 'review';
  return 'ready';
}

export function confidenceTone(value, threshold = 0.85) {
  if (value == null) return '';
  if (value < threshold - 0.15) return 'bad';
  if (value < threshold) return 'warn';
  return 'ok';
}

export function computeStats(documents) {
  const counts = { total: documents.length, processing: 0, error: 0, review: 0, ready: 0 };
  const confidences = [];
  const totals = {};
  let fieldsFound = 0;
  let fieldsTotal = 0;

  for (const doc of documents) {
    counts[displayStatus(doc)] += 1;
    const s = doc.summary;
    if (!s || doc.status !== 'completed') continue;
    if (s.avg_confidence != null) confidences.push(s.avg_confidence);
    fieldsFound += s.fields_found || 0;
    fieldsTotal += s.fields_total || 0;
    if (s.amount) {
      const key = s.currency || '—';
      totals[key] = (totals[key] || 0) + Number(s.amount);
    }
  }

  return {
    ...counts,
    avgConfidence: confidences.length ? confidences.reduce((a, b) => a + b, 0) / confidences.length : null,
    coverage: fieldsTotal ? fieldsFound / fieldsTotal : null,
    totals: Object.entries(totals).sort((a, b) => b[1] - a[1]),
  };
}

// Uploads per day for the last `days` days (oldest first).
export function dailyActivity(documents, days = 14) {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() - (days - 1));
  const buckets = Array.from({ length: days }, (_, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return { date: d, count: 0, failed: 0 };
  });
  for (const doc of documents) {
    const created = new Date(doc.created_at);
    const idx = Math.floor((created - start) / 86400000);
    if (idx >= 0 && idx < days) {
      buckets[idx].count += 1;
      if (doc.status === 'error') buckets[idx].failed += 1;
    }
  }
  return buckets;
}

export const FIELD_LABELS = [
  ['customer_info.name', 'Customer name'],
  ['customer_info.billing_address', 'Billing address'],
  ['customer_info.poc_contact', 'Contact / phone'],
  ['customer_info.email', 'Email'],
  ['document_info.date', 'Date'],
  ['document_info.doc_number', 'Document no.'],
  ['document_info.amount', 'Total amount'],
  ['document_info.po_number', 'PO number'],
];

// How often each field was found across processed documents.
export function fieldCoverage(documents) {
  const done = documents.filter((d) => d.status === 'completed' && d.summary?.field_status);
  const rows = FIELD_LABELS.map(([key, label]) => {
    const r = { key, label, ok: 0, low: 0, missing: 0 };
    done.forEach((d) => { r[d.summary.field_status[key] || 'missing'] += 1; });
    r.found = r.ok + r.low;
    return r;
  });
  const weakest = [...rows].sort((a, b) => a.found - b.found)[0];
  return { docs: done.length, rows, weakest: weakest && weakest.found < done.length ? weakest : null };
}

import { confidenceTone } from '../lib/status';

export default function ConfidenceMeter({ value, threshold = 0.85, width, variant = 'bar' }) {
  if (value == null) return <span className="confidence-text muted">—</span>;
  const pct = Math.round(value * 100);
  const tone = confidenceTone(value, threshold);

  if (variant === 'text') {
    return (
      <span className={`confidence-text tone-${tone}`} title={`Average OCR confidence: ${pct}%`}>
        {pct}%
      </span>
    );
  }

  return (
    <span className={`meter ${tone}`} title="Average OCR confidence">
      <span className="meter-track" style={width ? { width } : undefined}>
        <span className="meter-fill" style={{ width: `${pct}%` }} />
      </span>
      {pct}%
    </span>
  );
}

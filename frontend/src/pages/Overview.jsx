import { useMemo } from 'react';
import { ArrowRight, ArrowUpRight, Upload, ScanText, Highlighter, FileDown, Sparkles } from 'lucide-react';
import PageHeader from '../components/PageHeader';
import UploadDropzone from '../components/UploadDropzone';
import StatusBadge from '../components/StatusBadge';
import FileIcon from '../components/FileIcon';
import { dailyActivity, fieldCoverage } from '../lib/status';
import { compactNumber, formatMoney, greeting, percent, timeAgo } from '../lib/format';
import './overview.css';

function Sparkline({ values }) {
  const max = Math.max(1, ...values);
  const w = 220;
  const h = 56;
  const step = w / Math.max(1, values.length - 1);
  const points = values.map((v, i) => [i * step, h - 4 - (v / max) * (h - 12)]);
  const line = points.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const area = `${line} L${w},${h} L0,${h} Z`;
  const [lx, ly] = points[points.length - 1];
  return (
    <svg className="sparkline" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id="spark-fill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="var(--lime)" stopOpacity="0.35" />
          <stop offset="100%" stopColor="var(--lime)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill="url(#spark-fill)" />
      <path d={line} fill="none" stroke="var(--lime)" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      <circle cx={lx} cy={ly} r="3.5" fill="var(--lime)" />
    </svg>
  );
}

function Ring({ value }) {
  const r = 34;
  const c = 2 * Math.PI * r;
  const v = value ?? 0;
  return (
    <svg className="ring" viewBox="0 0 84 84" aria-hidden="true">
      <circle cx="42" cy="42" r={r} className="ring-track" />
      <circle
        cx="42" cy="42" r={r}
        className="ring-fill"
        strokeDasharray={`${c * v} ${c}`}
        transform="rotate(-90 42 42)"
      />
    </svg>
  );
}

function ActivityChart({ buckets }) {
  const max = Math.max(1, ...buckets.map((b) => b.count));
  const total = buckets.reduce((a, b) => a + b.count, 0);
  return (
    <div className="activity">
      <div className="activity-bars" role="img" aria-label={`${total} uploads in the last ${buckets.length} days`}>
        {buckets.map((b, i) => {
          const isToday = i === buckets.length - 1;
          return (
            <div className="bar-col" key={b.date.toISOString()}>
              <div className="bar-slot">
                <div
                  className={`bar ${isToday ? 'today' : ''} ${b.count === 0 ? 'zero' : ''}`}
                  style={{ height: `${b.count ? Math.max(8, (b.count / max) * 100) : 3}%` }}
                >
                  {b.failed > 0 && <span className="bar-failed" style={{ height: `${(b.failed / b.count) * 100}%` }} />}
                  {b.count > 0 && <span className="bar-tip mono">{b.count}</span>}
                </div>
              </div>
              <span className={`bar-label ${isToday ? 'today' : ''}`}>
                {isToday ? 'Today' : b.date.toLocaleDateString([], i % 2 ? { day: 'numeric' } : { weekday: 'short' })}
              </span>
            </div>
          );
        })}
      </div>
      <div className="activity-legend">
        <span><i className="lg processed" /> Uploaded</span>
        <span><i className="lg failed" /> Failed</span>
      </div>
    </div>
  );
}

function Onboarding({ onUpload, onFiles }) {
  const steps = [
    { icon: Upload, title: 'Upload', text: 'Drop PDFs or scans — several at once is fine.' },
    { icon: ScanText, title: 'We read it', text: 'Text layers are read directly; scans go through OCR.' },
    { icon: Highlighter, title: 'You check', text: 'Low-confidence values are highlighted on the page.' },
    { icon: FileDown, title: 'Export', text: 'Download clean JSON or CSV for Excel.' },
  ];
  return (
    <div className="onboarding">
      <div className="card onboarding-card rise">
        <span className="badge badge-lime"><Sparkles size={13} /> Start here</span>
        <h2 className="display">Turn paperwork into<br /><mark>clean, checked data.</mark></h2>
        <UploadDropzone onBrowse={onUpload} onFiles={onFiles} />
      </div>
      <ol className="steps">
        {steps.map(({ icon: Icon, title, text }, i) => (
          <li key={title} className="card rise" style={{ '--i': i + 2 }}>
            <span className="step-num mono">0{i + 1}</span>
            <Icon size={20} />
            <strong>{title}</strong>
            <p>{text}</p>
          </li>
        ))}
      </ol>
    </div>
  );
}

function OverviewSkeleton() {
  return (
    <div className="overview-grid">
      {[0, 1, 2, 3].map((i) => <div key={i} className="card kpi skeleton-card"><div className="skeleton" style={{ height: 120 }} /></div>)}
      <div className="card span-5 skeleton-card"><div className="skeleton" style={{ height: 240 }} /></div>
      <div className="card span-7 skeleton-card"><div className="skeleton" style={{ height: 240 }} /></div>
    </div>
  );
}

export default function Overview({ documents, stats, loaded, navigate, onUpload, onFiles }) {
  const buckets = useMemo(() => dailyActivity(documents, 14), [documents]);
  const coverage = useMemo(() => fieldCoverage(documents), [documents]);
  const recent = documents.slice(0, 6);
  const thisWeek = buckets.slice(-7).reduce((a, b) => a + b.count, 0);
  const completed = stats.ready + stats.review;
  const today = new Date().toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' });

  const subtitle = !documents.length
    ? 'Upload your first contract or invoice to get started.'
    : stats.review
      ? `${stats.review} document${stats.review > 1 ? 's have' : ' has'} values worth a second look.`
      : stats.processing
        ? `${stats.processing} document${stats.processing > 1 ? 's are' : ' is'} being read right now.`
        : 'Everything is extracted and checked. Nice.';

  return (
    <div className="page">
      <PageHeader
        eyebrow={today}
        title={<>{greeting()}.</>}
        subtitle={loaded ? subtitle : ' '}
        actions={documents.length > 0 && (
          <>
            {stats.review > 0 && (
              <button className="btn btn-secondary" onClick={() => navigate('/documents?status=review')}>
                <Highlighter size={16} /> Review queue
              </button>
            )}
            <button className="btn btn-primary" onClick={onUpload}><Upload size={16} /> Upload</button>
          </>
        )}
      />

      {!loaded ? (
        <OverviewSkeleton />
      ) : !documents.length ? (
        <Onboarding onUpload={onUpload} onFiles={onFiles} />
      ) : (
        <div className="overview-grid">
          {/* KPI: total */}
          <section className="card kpi kpi-hero rise" style={{ '--i': 0 }}>
            <div className="kpi-top">
              <span className="card-kicker">Documents processed</span>
              <span className="kpi-delta mono">+{thisWeek} this week</span>
            </div>
            <div className="kpi-value display">{compactNumber(completed)}</div>
            <Sparkline values={buckets.map((b) => b.count)} />
            <div className="kpi-foot">{stats.total} uploaded · {stats.error} failed</div>
          </section>

          {/* KPI: ready */}
          <button className="card kpi card-interactive rise" style={{ '--i': 1 }} onClick={() => navigate('/documents?status=ready')}>
            <div className="kpi-top">
              <span className="card-kicker">Ready to use</span>
              <ArrowUpRight size={16} className="kpi-arrow" />
            </div>
            <div className="kpi-value display">{stats.ready}</div>
            <div className="kpi-bar"><span style={{ width: `${stats.total ? (stats.ready / stats.total) * 100 : 0}%` }} /></div>
            <div className="kpi-foot">{stats.total ? Math.round((stats.ready / stats.total) * 100) : 0}% of all documents</div>
          </button>

          {/* KPI: review */}
          <button className={`card kpi card-interactive rise ${stats.review ? 'kpi-attention' : ''}`} style={{ '--i': 2 }}
            onClick={() => navigate('/documents?status=review')}>
            <div className="kpi-top">
              <span className="card-kicker">Needs review</span>
              <ArrowUpRight size={16} className="kpi-arrow" />
            </div>
            <div className="kpi-value display">{stats.review}</div>
            <div className="kpi-foot">
              {stats.review ? 'Low-confidence values to confirm' : 'Nothing waiting for you'}
            </div>
            <Highlighter className="kpi-watermark" size={64} strokeWidth={1.3} aria-hidden="true" />
          </button>

          {/* KPI: quality */}
          <section className="card kpi kpi-quality rise" style={{ '--i': 3 }}>
            <div className="kpi-top">
              <span className="card-kicker">Extraction quality</span>
            </div>
            <div className="quality-row">
              <div className="ring-wrap">
                <Ring value={stats.avgConfidence} />
                <span className="ring-label display">{percent(stats.avgConfidence)}</span>
              </div>
              <dl>
                <div><dt>Avg. confidence</dt><dd className="mono">{percent(stats.avgConfidence)}</dd></div>
                <div><dt>Fields found</dt><dd className="mono">{percent(stats.coverage)}</dd></div>
              </dl>
            </div>
          </section>

          {/* Upload */}
          <section className="card span-5 upload-card rise" style={{ '--i': 4 }}>
            <div className="card-head">
              <h2 className="card-title">Add documents</h2>
              <span className="muted small">Drag anywhere on the page</span>
            </div>
            <div className="card-pad">
              <UploadDropzone onBrowse={onUpload} onFiles={onFiles} />
            </div>
          </section>

          {/* Recent */}
          <section className="card span-7 recent-card rise" style={{ '--i': 5 }}>
            <div className="card-head">
              <h2 className="card-title">Recent documents</h2>
              <button className="card-link" onClick={() => navigate('/documents')}>View all <ArrowRight size={14} /></button>
            </div>
            <ul className="recent-list">
              {recent.map((doc) => (
                <li key={doc.doc_id}>
                  <button className="recent-row" onClick={() => navigate(`/documents/${doc.doc_id}`)}>
                    <FileIcon filename={doc.filename} size={34} />
                    <span className="recent-main">
                      <span className="recent-name">{doc.summary?.customer || doc.filename}</span>
                      <span className="recent-sub">{doc.summary?.customer ? doc.filename : doc.summary?.title || '—'}</span>
                    </span>
                    <span className="recent-amount mono">{formatMoney(doc.summary?.amount, doc.summary?.currency)}</span>
                    <StatusBadge doc={doc} />
                    <span className="recent-time">{timeAgo(doc.created_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>

          {/* Activity */}
          <section className="card span-7 rise" style={{ '--i': 6 }}>
            <div className="card-head">
              <h2 className="card-title">Activity</h2>
              <span className="muted small">Last 14 days</span>
            </div>
            <div className="card-pad"><ActivityChart buckets={buckets} /></div>
          </section>

          {/* Field coverage */}
          <section className="card span-5 coverage-card rise" style={{ '--i': 7 }}>
            <div className="card-head">
              <h2 className="card-title">Field coverage</h2>
              <span className="muted small">Across {coverage.docs} document{coverage.docs === 1 ? '' : 's'}</span>
            </div>
            <div className="card-pad">
              {coverage.docs ? (
                <>
                  <ul className="coverage-list">
                    {coverage.rows.map((r) => (
                      <li key={r.key}>
                        <span className="cov-label">{r.label}</span>
                        <span className="cov-bar" title={`${r.ok} found · ${r.low} low confidence · ${r.missing} missing`}>
                          <span className="ok" style={{ width: `${(r.ok / coverage.docs) * 100}%` }} />
                          <span className="low" style={{ width: `${(r.low / coverage.docs) * 100}%` }} />
                        </span>
                        <span className={`cov-pct mono ${r.found / coverage.docs < 0.5 ? 'weak' : ''}`}>
                          {Math.round((r.found / coverage.docs) * 100)}%
                        </span>
                      </li>
                    ))}
                  </ul>
                  <div className="coverage-legend">
                    <span><i className="lg ok" /> Found</span>
                    <span><i className="lg low" /> Low confidence</span>
                    <span><i className="lg missing" /> Missing</span>
                  </div>
                  {coverage.weakest && (
                    <p className="coverage-tip">
                      <b>{coverage.weakest.label}</b> is missing most often. Add its label wording to
                      <code className="mono"> config/fields.json</code> to improve extraction.
                    </p>
                  )}
                </>
              ) : (
                <p className="muted">Coverage appears once documents are processed.</p>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

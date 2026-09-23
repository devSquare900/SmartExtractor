import { useMemo } from 'react';
import { Plus, Trash2, Rows3, Layers, Hash, Type, Sparkles, CircleAlert, Crosshair, Sigma } from 'lucide-react';

const DEFAULT_COLUMNS = ['Item', 'Description', 'Amount'];
const SERIAL_HEADER = /^(sr|s\.?\s?no|no|#|item\s?no|sl)/i;

const toNumber = (text) => {
  if (text == null) return null;
  const cleaned = String(text).replace(/[,\s]/g, '').replace(/^[^\d-]+/, '');
  if (!/^-?\d+(\.\d+)?/.test(cleaned)) return null;
  const n = parseFloat(cleaned);
  return Number.isFinite(n) ? n : null;
};

const filled = (cells) => (cells || []).filter((c) => (c || '').trim()).length;

// A row with a single long text cell (e.g. "Summary of Technical Requirement DR") is a section title.
const isGroupRow = (row, columnCount) => {
  const cells = row.cells || [];
  if (columnCount < 2 || filled(cells) !== 1) return false;
  const text = cells.find((c) => (c || '').trim()) || '';
  return text.trim().length >= 14 && toNumber(text) === null;
};

function analyseColumns(columns, rows) {
  const dataRows = rows.filter((r) => !isGroupRow(r, columns.length));
  return columns.map((name, ci) => {
    const values = dataRows.map((r) => (r.cells?.[ci] || '').trim()).filter(Boolean);
    const nums = values.map(toNumber).filter((n) => n !== null);
    const numeric = values.length > 0 && nums.length / values.length >= 0.6;
    const serial = ci === 0 && (SERIAL_HEADER.test(name.trim()) || (numeric && nums.every((n) => Number.isInteger(n) && n < 1000)));
    return {
      name,
      numeric: numeric && !serial,
      serial,
      max: nums.length ? Math.max(...nums) : 0,
      total: nums.reduce((a, b) => a + b, 0),
      count: nums.length,
    };
  });
}

export default function LineItems({ lineItems, threshold, onChange, onFocusRow, onlyToCheck }) {
  const { rows, columns, meta, serials } = useMemo(() => {
    const r = lineItems?.rows || [];
    const cols = lineItems?.columns?.length ? lineItems.columns : DEFAULT_COLUMNS;
    // Item numbers restart after each section title.
    const nums = [];
    r.forEach((row, i) => {
      nums.push(isGroupRow(row, cols.length) ? 0 : (i > 0 ? nums[i - 1] : 0) + 1);
    });
    return { rows: r, columns: cols, meta: analyseColumns(cols, r), serials: nums };
  }, [lineItems]);

  const isLow = (row) => !row.manual && typeof row.confidence === 'number' && row.confidence < threshold;
  const groups = rows.filter((r) => isGroupRow(r, columns.length)).length;
  const dataCount = rows.length - groups;
  const recoveredCount = rows.reduce((a, r) => a + (r.manual ? 0 : (r.recovered?.length || 0)), 0);
  const emptyCells = rows.reduce((a, r) => (isGroupRow(r, columns.length) ? a : a + columns.length - filled(r.cells)), 0);
  const numericCols = meta.filter((m) => m.numeric && m.count > 1);

  const setCell = (ri, ci, value) => onChange((d) => {
    const r = d.line_items.rows[ri];
    r.cells = r.cells || [];
    r.cells[ci] = value;
    r.manual = true;
  });
  const deleteRow = (ri) => onChange((d) => { d.line_items.rows.splice(ri, 1); });
  const addRow = () => onChange((d) => {
    d.line_items = d.line_items || { columns: [], rows: [] };
    if (!d.line_items.columns?.length) d.line_items.columns = [...DEFAULT_COLUMNS];
    d.line_items.rows.push({ cells: d.line_items.columns.map(() => ''), manual: true });
  });

  return (
    <section className="card field-card li-card rise" style={{ '--i': 3 }}>
      <div className="card-head">
        <h2 className="card-title">
          <span className="title-icon"><Rows3 size={16} /></span>
          Line items
        </h2>
        <button className="btn btn-ghost btn-sm" onClick={addRow}><Plus size={15} /> Add row</button>
      </div>

      {rows.length > 0 && (
        <div className="li-stats">
          <span className="li-stat"><b className="mono">{dataCount}</b> items</span>
          {groups > 0 && <span className="li-stat"><Layers size={13} /><b className="mono">{groups + 1}</b> sections</span>}
          <span className="li-stat"><b className="mono">{columns.length}</b> columns</span>
          {recoveredCount > 0 && (
            <span className="li-stat lime" title="These cells were empty after OCR and were filled by re-reading just that cell">
              <Sparkles size={13} /><b className="mono">{recoveredCount}</b> auto-filled
            </span>
          )}
          {emptyCells > 0 && <span className="li-stat warn"><b className="mono">{emptyCells}</b> empty cells</span>}
        </div>
      )}

      {rows.length ? (
        <div className="li-scroll">
          <table className="li-table">
            <thead>
              <tr>
                {meta.map((m, i) => (
                  <th key={i} className={m.numeric ? 'num' : m.serial ? 'serial' : ''}>
                    <span className="th-inner">
                      {m.numeric ? <Hash size={11} /> : !m.serial && <Type size={11} />}
                      {m.name}
                    </span>
                  </th>
                ))}
                <th aria-label="Row actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row, ri) => {
                const group = isGroupRow(row, columns.length);
                if (onlyToCheck && !isLow(row) && !(row.recovered?.length && !row.manual)) return null;

                if (group) {
                  const ci = (row.cells || []).findIndex((c) => (c || '').trim());
                  return (
                    <tr key={ri} className="li-group">
                      <td colSpan={columns.length}>
                        <span className="group-inner">
                          <Layers size={14} />
                          <input
                            className="li-input group-input"
                            value={row.cells[ci]}
                            aria-label="Section title"
                            onChange={(e) => setCell(ri, ci, e.target.value)}
                            onFocus={() => onFocusRow(row, 'Section')}
                          />
                        </span>
                      </td>
                      <td className="li-act">
                        <button className="btn btn-ghost btn-sm btn-icon" aria-label="Delete section" onClick={() => deleteRow(ri)}>
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  );
                }

                const serialNumber = serials[ri];
                const low = isLow(row);
                return (
                  <tr key={ri} className={`${low ? 'is-low' : ''}`}>
                    {meta.map((m, ci) => {
                      const value = row.cells?.[ci] ?? '';
                      const recovered = !row.manual && row.recovered?.includes(ci);
                      const empty = !value.trim();
                      const n = m.numeric ? toNumber(value) : null;
                      return (
                        <td
                          key={ci}
                          className={`${m.numeric ? 'num' : ''} ${m.serial ? 'serial' : ''} ${recovered ? 'recovered' : ''} ${empty ? 'empty' : ''}`}
                        >
                          {m.numeric && n !== null && m.max > 0 && (
                            <span className="num-bar" style={{ width: `${Math.max(6, (n / m.max) * 100)}%` }} aria-hidden="true" />
                          )}
                          <input
                            className="li-input"
                            value={value}
                            placeholder={m.serial ? String(serialNumber) : '—'}
                            aria-label={`Row ${ri + 1}, ${m.name}`}
                            title={recovered ? 'Auto-filled: this cell was re-read from the page image' : undefined}
                            onChange={(e) => setCell(ri, ci, e.target.value)}
                            onFocus={() => onFocusRow(row, `Row ${serialNumber}`)}
                          />
                          {recovered && <Sparkles size={11} className="recovered-icon" aria-label="Auto-filled" />}
                        </td>
                      );
                    })}
                    <td className="li-act">
                      <span className="li-act-inner">
                        {low && <CircleAlert size={14} className="warn-icon" aria-label="Low confidence" />}
                        {row.box && (
                          <button className="btn btn-ghost btn-sm btn-icon li-locate" aria-label={`Show row ${ri + 1} on the page`}
                            onClick={() => onFocusRow(row, `Row ${serialNumber}`)}>
                            <Crosshair size={14} />
                          </button>
                        )}
                        <button className="btn btn-ghost btn-sm btn-icon li-del" aria-label={`Delete row ${ri + 1}`} onClick={() => deleteRow(ri)}>
                          <Trash2 size={14} />
                        </button>
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
            {numericCols.length > 0 && !onlyToCheck && (
              <tfoot>
                <tr>
                  {meta.map((m, i) => (
                    <td key={i} className={m.numeric ? 'num' : ''}>
                      {i === 0 && <span className="foot-label"><Sigma size={13} /> Total</span>}
                      {m.numeric && m.count > 1 && <span className="mono">{m.total.toLocaleString()}</span>}
                    </td>
                  ))}
                  <td />
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      ) : (
        <div className="li-empty">
          <Rows3 size={22} />
          <p>No table was found in this document.</p>
          <button className="btn btn-secondary btn-sm" onClick={addRow}><Plus size={14} /> Add a row manually</button>
        </div>
      )}
    </section>
  );
}

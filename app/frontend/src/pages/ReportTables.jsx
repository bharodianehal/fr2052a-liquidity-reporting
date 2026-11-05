import React, { useState, useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import StepHeader from '../components/StepHeader';
import { TrendingUp, Download, AlertTriangle } from 'lucide-react';

const SECTIONS = [
  ['Inflows', 'Cash and assets the firm will receive', 'bg-emerald-50 border-emerald-200'],
  ['Outflows', 'Cash the firm will pay out', 'bg-red-50 border-red-200'],
  ['Supplemental', 'Information that supports the inflows and outflows', 'bg-blue-50 border-blue-200'],
  ['Comments', 'Free-text explanations to the Federal Reserve', 'bg-slate-50 border-slate-200'],
];
const ENTITIES = [['ENT001', 'Consolidated BHC'], ['ENT002', 'Bank (solo)'], ['ENT003', 'Broker-dealer (solo)']];
const HIDE = new Set(['as_of_date', 'record_key', 'validation_status', 'validation_issues', 'adjustment_ids']);
const num = (v, d = 2) => (v == null || v === '' ? '' : isNaN(v) ? String(v) : parseFloat(v).toLocaleString('en-US', { maximumFractionDigits: d }));
const pct = (v) => (v == null ? '' : `${parseFloat(v) >= 0 ? '+' : ''}${parseFloat(v).toFixed(1)}%`);

// Step 3: the FR 2052a as the Federal Reserve structures it - Inflows (I.A, I.U, I.S, I.O), Outflows (O.D, O.W, O.S, O.O),
// Supplemental (S.DC, S.L, S.B, S.I, S.FX) and Comments (S.C) - per reporting entity, each table with the Instructions' fields
// in order (Mandatory / Dependent), exactly as it is filed in the 6G file.
export default function ReportTables({ date, embedded }) {
  const [tables, setTables] = useState([]);
  const [summary, setSummary] = useState({ tables: [] });
  const [variance, setVariance] = useState([]);
  const [products, setProducts] = useState({});
  const [entity, setEntity] = useState('ENT001');
  const [code, setCode] = useState('O.D');
  const [detail, setDetail] = useState(null);
  const [pid, setPid] = useState('');
  const [msg, setMsg] = useState('');

  useEffect(() => {
    api.getTables().then(setTables).catch((e) => setMsg(e.message));
    api.getConfig('products').then((p) => setProducts(Object.fromEntries(p.map((x) => [x.product_id, x.product_name])))).catch(() => {});
  }, []);
  useEffect(() => {
    if (!date) return;
    api.wbEntitySummary(date).then(setSummary).catch((e) => setMsg(e.message));
    api.wbVariance(date).then(setVariance).catch(() => setVariance([]));
  }, [date]);
  useEffect(() => { if (date && code) { setDetail(null); setPid(''); api.getTableRecords(date, code).then(setDetail).catch((e) => setMsg(e.message)); } }, [date, code]);

  const stat = (c) => summary.tables.find((t) => t.reporting_entity === entity && t.table_code === c);
  const vt = (c) => variance.find((v) => v.reporting_entity === entity && v.table_code === c && v.series_level === 'TABLE');
  const t = tables.find((x) => x.table_code === code);
  const rows = useMemo(() => (detail?.rows || []).filter((r) => (code === 'S.C' || r.reporting_entity === entity) && (!pid || r.product_id === pid)), [detail, entity, pid, code]);
  const cols = (detail?.fields || []).filter((f) => !HIDE.has(f.column_name) && f.column_name !== 'reporting_entity');
  const pids = [...new Set((detail?.rows || []).filter((r) => r.reporting_entity === entity).map((r) => r.product_id))].sort();
  const v = vt(code);

  return (
    <div className="space-y-5">
      {embedded ? <p className="text-xs text-slate-500">The structure is the Federal Reserve's: FR 2052a Instructions, Data Tables (p.84-85), and the 6G schema. Each table exactly as it goes into the 6G file.</p>
        : <StepHeader n={4} date={date}>The structure is the Federal Reserve's: FR 2052a Instructions, Data Tables (p.84-85), and the 6G schema.</StepHeader>}
      {msg && <div className="text-xs text-red-600">{msg}</div>}

      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-500">Reporting entity:</span>
        {ENTITIES.map(([e, label]) => (
          <button key={e} onClick={() => setEntity(e)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium border ${entity === e ? 'bg-navy-900 text-white border-navy-900' : 'bg-white border-slate-200 text-slate-700'}`}>{e} {label}</button>
        ))}
        <a href={api.downloadExcel(date)} className="ml-auto flex items-center gap-1 text-xs text-blue-700 hover:underline"><Download className="w-3.5 h-3.5" />All tables (Excel)</a>
      </div>

      <div className="grid grid-cols-4 gap-4">
        {SECTIONS.map(([section, desc, cls]) => (
          <div key={section} className={`rounded-xl border p-3 ${cls}`}>
            <div className="text-sm font-semibold text-navy-900">{section}</div>
            <div className="text-[11px] text-slate-500 mb-2">{desc}</div>
            <div className="space-y-1.5">
              {tables.filter((x) => x.section === section).map((x) => {
                const s = stat(x.table_code); const vv = vt(x.table_code);
                return (
                  <button key={x.table_code} onClick={() => setCode(x.table_code)}
                    className={`w-full text-left rounded-lg px-2.5 py-1.5 bg-white border ${code === x.table_code ? 'border-blue-500 ring-1 ring-blue-500' : 'border-slate-200 hover:border-blue-300'}`}>
                    <div className="flex items-center gap-2 text-xs">
                      <span className="font-mono font-semibold w-9">{x.table_code}</span>
                      <span className="flex-1 truncate">{x.table_name.replace(/^(Inflows|Outflows|Supplemental)-/, '')}</span>
                      {vv?.is_anomaly && <AlertTriangle className="w-3.5 h-3.5 text-amber-600" title="Movement outside the expected range" />}
                    </div>
                    <div className="text-[10px] text-slate-500 ml-11">{s ? `${s.records} records | USD ${num(s.usd, 0)} mm` : x.table_code === 'S.C' ? 'all entities' : 'not reported by this entity'}</div>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {t && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
          <div className="px-5 py-3 border-b border-slate-100 flex flex-wrap items-center gap-3">
            <div>
              <div className="text-sm font-semibold text-navy-900">{t.table_code} {t.table_name} - {code === 'S.C' ? 'all reporting entities' : entity}</div>
              <div className="text-[11px] text-slate-500">6G report type <span className="font-mono">{t.xml_report_type}</span> | {rows.length} records | one record per unique combination of the reporting fields</div>
            </div>
            {v && (
              <div className={`text-[11px] px-2.5 py-1 rounded-lg flex items-center gap-1 ${v.is_anomaly ? 'bg-amber-50 text-amber-800' : 'bg-slate-50 text-slate-600'}`}>
                <TrendingUp className="w-3.5 h-3.5" />Table total USD {num(v.amount_usd, 0)} mm, {pct(v.change_pct)} vs prior day; AI expected {num(v.lower_usd, 0)} - {num(v.upper_usd, 0)}
                {v.is_anomaly ? ' - outside the range: explain it in a comment at Generate 6G & release' : ''}</div>
            )}
            {code !== 'S.C' && pids.length > 1 && (
              <select value={pid} onChange={(e) => setPid(e.target.value)} className="ml-auto text-xs border border-slate-200 rounded px-2 py-1">
                <option value="">All products ({pids.length})</option>
                {pids.map((p) => <option key={p} value={p}>{p} {products[p] || ''}</option>)}
              </select>
            )}
          </div>
          <div className="overflow-x-auto max-h-[36rem] overflow-y-auto">
            <table className="w-full text-[11px]">
              <thead className="bg-slate-50 sticky top-0">
                <tr>
                  {code === 'S.C' && <th className="text-left px-2 py-1.5 align-bottom">Reporting Entity</th>}
                  {cols.map((f) => (
                    <th key={f.column_name} className="text-left px-2 py-1.5 align-bottom whitespace-nowrap">
                      {f.field_name}<div className={`text-[9px] font-normal ${f.field_class === 'Mandatory' ? 'text-red-600' : 'text-slate-400'}`}>{f.field_class}</div></th>
                  ))}
                  <th className="text-right px-2 py-1.5 align-bottom">Positions</th><th className="px-2" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.record_key} className="border-t border-slate-100 hover:bg-slate-50">
                    {code === 'S.C' && <td className="px-2 py-1">{r.reporting_entity}</td>}
                    {cols.map((f) => (
                      <td key={f.column_name} className={`px-2 py-1 whitespace-nowrap ${typeof r[f.column_name] === 'number' || /amount|value/.test(f.column_name) ? 'text-right' : ''}`}
                        title={f.column_name === 'product_id' ? products[r.product_id] : undefined}>
                        {f.column_name === 'product_id' ? <span className="font-mono">{r.product_id}</span> : num(r[f.column_name], 4)}
                      </td>
                    ))}
                    <td className="px-2 py-1 text-right">{r.record_count}</td>
                    <td className="px-2 py-1"><Link to={`/lineage?key=${r.record_key}`} className="text-blue-700 hover:underline">trace</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

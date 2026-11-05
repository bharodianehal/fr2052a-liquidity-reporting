import React, { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api';
import PositionJourney from '../components/PositionJourney';
import { GitBranch, FileCode2, Table2, Layers, Database, FileInput, ArrowDown, Search, AlertTriangle } from 'lucide-react';

const num = (v, d = 2) => (v == null || v === '' ? '--' : parseFloat(v).toLocaleString('en-US', { maximumFractionDigits: d }));
const short = (p) => (p || '').split('/').slice(-2).join('/');
const SKIP = new Set(['as_of_date', 'record_key', 'record_count', 'validation_status', 'adjustment_ids']);

function Card({ icon: Icon, title, sub, children }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
      <div className="px-4 py-2.5 border-b border-slate-100 flex items-center gap-2">
        <Icon className="w-4 h-4 text-blue-600" /><span className="text-sm font-semibold text-navy-900">{title}</span>
        {sub && <span className="text-xs text-slate-500">{sub}</span>}
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}
const Down = () => <div className="flex justify-center"><ArrowDown className="w-4 h-4 text-slate-300" /></div>;

// Lineage: the day's data flow with counts at every stage, and any record traced end to end - backward from a filed record
// to its landing file (with how each field was derived), or forward from a source record to every filed record it is in.
export default function Lineage({ date }) {
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState('trace');
  const [journey, setJourney] = useState(null);
  const [flow, setFlow] = useState(null);
  const [q, setQ] = useState(params.get('position') || params.get('key') || params.get('source') || '');
  const [rec, setRec] = useState(null);
  const [fwd, setFwd] = useState(null);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);


  const trace = async (value) => {
    const v = (value ?? q).trim();
    if (!v) return;
    setBusy(true); setMsg(''); setRec(null); setFwd(null); setJourney(null);
    try {
      if (/^[0-9a-f]{64}$/.test(v)) { setRec(await api.wbLineageRecord(date, v)); setParams({ key: v }); }
      else {
        const j = await api.wbLineagePosition(date, v);
        if (j.choose) { setFwd(await api.wbLineageSource(date, v)); setParams({ source: v }); }
        else { setJourney(j); setParams({ position: j.position_id }); }
      }
    } catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };
  useEffect(() => { if (tab === 'trace' && q && date) trace(q); }, [date]); // eslint-disable-line

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-navy-900 flex items-center gap-2"><GitBranch className="w-5 h-5" /> Lineage - {date}</h1>
        <p className="text-sm text-slate-500 mt-1">Follow one position step by step from the source file to its element in the 6G file, with every enrichment
          and how it was derived; or trace a reported record back to its positions and source records. For all records of a feed at every step, see Dashboard > Source to Report.</p>
      </div>
      <div className="flex gap-2">
        {[].map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} className={`px-3 py-1.5 rounded-lg text-xs font-medium border ${tab === k ? 'bg-navy-900 text-white border-navy-900' : 'bg-white border-slate-200 text-slate-700'}`}>{l}</button>
        ))}
      </div>
      {msg && <div className="text-xs text-red-600">{msg}</div>}

      {tab === 'trace' && (
        <div className="space-y-4">
          <div className="flex gap-2">
            <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && trace()}
              placeholder="A position (e.g. DEP-2026-02-27-00001#INS) - step by step to the 6G XML; a source record id; or a filed record key (backward)"
              className="flex-1 border border-slate-200 rounded-lg px-3 py-2 text-sm font-mono" />
            <button disabled={busy} onClick={() => trace()} className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-blue-600 text-white disabled:opacity-40">
              <Search className="w-4 h-4" /> Trace</button>
          </div>
          {busy && <div className="text-xs text-slate-500">Tracing through Delta...</div>}

          {journey && <PositionJourney j={journey} onTrace={(k) => { setQ(k); trace(k); }} />}

          {rec && (
            <div className="space-y-1.5">
              <Card icon={FileCode2} title="6G XML" sub={`report type ${rec.xml_report_type}, reportID ${rec.fields.report_id ?? '--'}`}>
                <div className="text-xs space-y-0.5">{rec.files.map((f) => (
                  <div key={f.file_type}><span className="font-mono">{f.file_name}</span> - {f.file_type}, run {f.run_number}, 6G version {f.version}, XSD {f.xsd_valid ? 'valid' : 'INVALID'}, {String(f.release_status).replace(/_/g, ' ')}</div>
                ))}</div>
              </Card>
              <Down />
              <Card icon={Table2} title={`Filed record - ${rec.record.reporting_entity} ${rec.record.table_code} ${rec.record.product_id}`} sub={`${rec.record.record_count} position(s) aggregated on the 6G report key`}>
                <div className="grid grid-cols-4 gap-x-6 gap-y-1 text-xs">
                  {Object.entries(rec.fields).filter(([k, v]) => !SKIP.has(k) && v != null && v !== '').map(([k, v]) => (
                    <div key={k}><span className="text-slate-400">{k.replace(/_/g, ' ')}: </span><span className="font-medium">{String(v)}</span></div>
                  ))}
                </div>
                {rec.adjustments.length > 0 && <div className="mt-3 text-xs text-purple-800 bg-purple-50 rounded p-2">
                  {rec.adjustments.map((a) => <div key={a.adjustment_id}>Adjustment {a.adjustment_id}: {a.column_name} {num(a.amount, 4)} - {a.reason} (prepared {a.preparer}, {a.status.toLowerCase()} {a.approver || ''})</div>)}</div>}
                {rec.checks.length > 0 && <div className="mt-3 text-xs text-red-800 bg-red-50 rounded p-2 flex gap-1.5"><AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                  <div>{rec.checks.map((c, k) => <div key={k}>{c.rule_id} {c.rule_name} ({c.severity}): {c.failure_detail}</div>)}</div></div>}
              </Card>
              <Down />
              <Card icon={Layers} title="Positions (Silver) - how each field was derived" sub={`${rec.positions.length} position(s)`}>
                <div className="overflow-x-auto">
                  <table className="w-full text-[11px]">
                    <thead className="text-slate-500"><tr><th className="text-left">Position</th><th className="text-right">Amount</th><th className="text-left pl-2">Booked at / scope</th>
                      <th className="text-left">PID rule (first match)</th><th className="text-left">Counterparty (customer master)</th><th className="text-left">Maturity</th>
                      <th className="text-left">Collateral</th><th className="text-left">Insured / lendable</th></tr></thead>
                    <tbody>{rec.positions.map((p) => (
                      <tr key={p.position_id} className="border-t border-slate-100 align-top">
                        <td className="py-1 font-mono"><button className="text-blue-700 hover:underline" onClick={() => { setQ(p.position_id); trace(p.position_id); }}>{p.position_id}</button></td><td className="text-right">{num(p.amount)}</td>
                        <td className="pl-2">{p.booking_entity}<div className="text-slate-400">{p.relationship}{p.internal_counterparty ? ` - ${p.internal_counterparty}` : ''}</div></td>
                        <td>{p.source_product_code} -&gt; {p.standard_product_type} -&gt; <b>{p.product_id}</b><div className="text-slate-400 font-mono">{p.pid_rule_id} #{p.rule_priority}: {p.rule_condition}</div></td>
                        <td>{p.counterparty || '--'}{p.gsib ? ` (G-SIB ${p.gsib})` : ''}<div className="text-slate-400">{p.customer_id || ''}{p.customer_approved_by ? ` approved by ${p.customer_approved_by}` : ''}</div></td>
                        <td>{p.maturity_bucket} ({p.maturity_date || 'open'})<div className="text-slate-400">{p.maturity_basis}</div></td>
                        <td>{p.collateral_class || '--'}<div className="text-slate-400">{p.collateral_basis}</div></td>
                        <td>{p.insured || ''}<div className="text-slate-400">{p.insured_basis || ''}{p.lendable_basis ? ` | ${p.lendable_basis}` : ''}</div></td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              </Card>
              <Down />
              <Card icon={Database} title="Source records (DQ-passed) and landing files" sub={`${rec.sources.length} source record(s)`}>
                <table className="w-full text-[11px]">
                  <thead className="text-slate-500"><tr><th className="text-left">Record</th><th className="text-left">System / code</th><th className="text-left">Customer / collateral</th>
                    <th className="text-right">Principal</th><th className="text-right">Market value</th><th className="text-left pl-2">DQ</th><th className="text-left">Landing file</th><th className="text-left">Ingested</th></tr></thead>
                  <tbody>{rec.sources.map((s) => (
                    <tr key={s.record_id} className="border-t border-slate-100 align-top">
                      <td className="py-1 font-mono"><button className="text-blue-700 hover:underline" onClick={() => { setQ(s.record_id); trace(s.record_id); }}>{s.record_id}</button></td>
                      <td>{s.source_system}<div className="text-slate-400 font-mono">{s.source_product_code} {s.instrument_type ? `(${s.instrument_type})` : ''}</div></td>
                      <td>{s.customer_id || ''}<div className="text-slate-400">{s.collateral_id || ''}</div></td>
                      <td className="text-right">{num(s.principal_amount)} {s.currency}</td><td className="text-right">{num(s.market_value)}</td>
                      <td className="pl-2">{s.dq_status}</td>
                      <td className="font-mono flex items-center gap-1"><FileInput className="w-3 h-3 text-slate-400" />{short(s.landing_file)}</td>
                      <td>{String(s.ingested_at || '').replace('T', ' ').slice(0, 19)}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </Card>
            </div>
          )}

          {fwd && (
            <div className="space-y-1.5">
              <Card icon={Database} title={`Source record ${fwd.record_id}`} sub={`${fwd.positions.length} calculated position(s)`}>
                {fwd.held.map((h, k) => <div key={k} className="text-xs text-amber-800 mb-1">
                  {h.state === 'quarantined' ? 'Data quality gate' : 'Held out of the filing'}: {h.reason}{h.state === 'quarantined' && /duplicate/i.test(h.reason || '') ? ' - the first copy was kept' : ''}</div>)}
                <table className="w-full text-[11px]"><tbody>{fwd.positions.map((p) => (
                  <tr key={p.position_id} className="border-t border-slate-100"><td className="py-1 font-mono"><button className="text-blue-700 hover:underline" onClick={() => { setQ(p.position_id); trace(p.position_id); }}>{p.position_id}</button></td><td>part {p.part}</td>
                    <td className="font-semibold">{p.product_id}</td><td className="font-mono text-slate-500">{p.pid_rule_id}</td><td>{p.booking_entity}</td>
                    <td className="text-right">{num(p.principal_amount ?? p.market_value)} {p.currency}</td></tr>
                ))}</tbody></table>
              </Card>
              <Down />
              <Card icon={Table2} title="Filed in" sub={`${fwd.filed.length} filed record(s) across the reporting entities`}>
                {fwd.eliminated.map((e, k) => <div key={k} className="text-xs text-slate-500">Eliminated in {e.reporting_entity}: intercompany with {e.counterparty_legal_entity}</div>)}
                <table className="w-full text-[11px]">
                  <thead className="text-slate-500"><tr><th className="text-left">Entity</th><th className="text-left">Table / PID</th><th className="text-left">Counterparty / bucket</th>
                    <th className="text-right">This position</th><th className="text-right">Filed amount</th><th className="text-right">Positions in record</th><th /></tr></thead>
                  <tbody>{fwd.filed.map((f, k) => (
                    <tr key={k} className="border-t border-slate-100"><td className="py-1">{f.reporting_entity}<div className="text-slate-400">{f.relationship}</div></td>
                      <td>{f.table_code} <b>{f.product_id}</b></td><td>{f.counterparty || ''} {f.maturity_bucket || ''}</td>
                      <td className="text-right">{num(f.amount)}</td><td className="text-right">{num(f.reported_amount)}</td><td className="text-right">{f.record_count}</td>
                      <td className="pl-2"><button className="text-blue-700 hover:underline" onClick={() => { setQ(f.record_key); trace(f.record_key); }}>trace record</button></td></tr>
                  ))}</tbody>
                </table>
              </Card>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

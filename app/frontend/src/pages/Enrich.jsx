import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api';
import AgentEvidence, { BulkApprove } from '../components/AgentEvidence';
import StepHeader from '../components/StepHeader';
import { Corrector } from './Validate';
import { StepTabs, Rerun, QueueFilters, Queue, Detail, AiFix, Actions, Btn, Decided, AllClear, filterQueue, queueCounts, RUNNING } from '../components/StepKit';
import { Check, PencilLine, Ban, ChevronRight, ChevronLeft, X } from 'lucide-react';

const SECTIONS = ['Inflows', 'Outflows', 'Supplemental'];
const num = (v, d = 1) => (v == null || v === '' ? '' : isNaN(v) ? String(v) : parseFloat(v).toLocaleString('en-US', { maximumFractionDigits: d }));
const S = { PROPOSED: 'review', ACCEPTED: 'done', REJECTED: 'excluded' };

// One item that needs a person: what is wrong and what it affects, the AI-suggested fix, the agent's evidence, then accept / fix manually / exclude.
function ReviewItem({ date, item, onDone }) {
  const [mode, setMode] = useState(null);
  const [edits, setEdits] = useState({});
  const [note, setNote] = useState('');
  const [msg, setMsg] = useState('');
  useEffect(() => { setMode(null); setEdits({}); setNote(''); setMsg(''); }, [item.id]);
  const decide = async (decision, e) => {
    setMsg('');
    try { await api.wbAiDecide(item.id, decision, note, e); onDone(); } catch (x) { setMsg(x.message); }
  };
  const isIssue = item.kind === 'Enrichment issue';
  return (
    <Detail tag={item.kind} title={item.title} s={item.s} sub={`Affects: ${item.affects}${item.context ? ` | ${item.context}` : ''}`}>
      <div className="text-sm text-slate-800">{item.problem}</div>
      {isIssue ? (
        <Corrector date={date} target={{ position_id: item.position_id }} onClose={onDone} onSaved={() => setMsg('Correction saved - applied by the next validation run.')} />
      ) : (<>
        {item.s !== 'review' && <Decided>Decided{item.decided_by ? ` by ${item.decided_by}` : ''}. Re-run the enrichment so the pipeline uses it.</Decided>}
        <AiFix confidence={item.confidence} title={Object.entries(item.suggestion || {}).filter(([, v]) => v).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`).join(' | ') || 'No suggestion'} rationale={item.rationale} />
        {item.s === 'review' && (
          <Actions>
            <Btn primary icon={Check} onClick={() => decide('ACCEPTED')}>Accept AI fix</Btn>
            <Btn icon={PencilLine} active={mode === 'manual'} onClick={() => setMode(mode === 'manual' ? null : 'manual')}>Fix manually</Btn>
            <Btn icon={Ban} active={mode === 'exclude'} onClick={() => setMode(mode === 'exclude' ? null : 'exclude')}>Exclude</Btn>
          </Actions>)}
        {mode === 'manual' && (
          <div className="space-y-2">
            <div className="grid grid-cols-2 gap-2">{item.editable.map((k) => (
              <label key={k} className="text-[11px]"><span className="text-slate-400">{k.replace(/_/g, ' ')}</span>
                <input defaultValue={(item.suggestion || {})[k] ?? ''} onChange={(e) => setEdits({ ...edits, [k]: e.target.value || null })} className="w-full border border-slate-200 rounded px-2 py-1" /></label>))}</div>
            <div className="flex gap-2"><input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)" className="flex-1 border border-slate-200 rounded px-2 py-1.5 text-xs" />
              <button disabled={!Object.keys(edits).length} onClick={() => decide('ACCEPTED', edits)} className="px-4 py-1.5 rounded-lg text-xs font-medium bg-blue-600 text-white disabled:opacity-40">Save my fix</button></div>
          </div>)}
        {mode === 'exclude' && (
          <div className="flex gap-2"><input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why it stays out of the report (required)" className="flex-1 border border-slate-200 rounded px-2 py-1.5 text-xs" />
            <button disabled={!note.trim()} onClick={() => decide('REJECTED')} className="px-4 py-1.5 rounded-lg text-xs font-medium bg-slate-700 text-white disabled:opacity-40">Exclude</button></div>)}
        <AgentEvidence date={date} kind="ai" refKey={item.id} />
      </>)}
      {msg && <div className="text-xs text-blue-700">{msg}</div>}
    </Detail>
  );
}

// The per-position basis codes notebook 03 writes, in plain words (a holiday / weekend roll is appended after " - ").
const BASIS = {
  CONTRACTUAL: 'contractual maturity date -> Appendix IV-a bucket (calendar days after the as-of date)',
  DRAWDOWN: 'effective drawdown date of the facility -> bucket', NOTICE: 'notice period -> bucket',
  OPTION_EARLIEST: 'option: the earliest possible date (outflow) -> bucket', OPTION_LATEST: 'option: the latest possible date (inflow) -> bucket',
  SECURITY: 'security id -> Collateral Class (security master, Appendix III)', 'LINKED (2 pieces, lowest level)': 'linked collateral: the lowest-liquidity piece sets the Collateral Class',
  'GENERIC (substitutable)': 'substitutable collateral: the generic class of the eligible set',
  SOURCE: 'insured flag as sent by the source system', FDIC_370_ALLOCATION: 'FDIC Part 370 allocation: the balance split into insured (up to USD 250k per ownership right) and uninsured',
  'CALCULATED (pledge-venue haircut)': 'market value less the pledge-venue haircut', 'NOT LENDABLE': 'not lendable at any pledge venue -> 0',
};
const howOf = (f, row) => {
  const empty = row[f.column] == null || row[f.column] === '';
  if (empty && f.field_class !== 'Mandatory') return 'not applicable to this position';
  if (f.column === 'maturity_bucket' && !row.contract_maturity_date && row.maturity_bucket === 'Open') return 'no contractual maturity (e.g. a demand deposit or an open loan) -> Open';
  return f.basis ? (row[f.basis] ? basisText(row[f.basis]) : 'not applicable to this position') : f.how;
};
const basisText = (v) => { const [code, roll] = String(v).split(' - '); return (BASIS[code] || code) + (roll ? ` - ${roll}` : ''); };
const show = (v) => (v == null || v === '' ? '' : typeof v === 'number' || !isNaN(v) && String(v).includes('.') ? num(v, 2) : String(v));

// One position, field by field: the FR 2052a value, the source column it came from, and how it was derived - then the PID rule.
function HowEnriched({ row, fields, onClose }) {
  if (!row) return null;
  return (
    <div className="border-t-2 border-blue-200 bg-blue-50/30 p-4 space-y-3">
      <div className="flex items-center gap-2 text-sm"><span className="font-mono font-semibold text-navy-900">{row.position_id}</span>
        <span className="text-xs text-slate-500">from source record <span className="font-mono">{row.record_id}</span>{row.part ? ` (part: ${row.part})` : ''} - {row.source_system} {row.source_product_code}, booked at {row.booking_entity}</span>
        <a href={`/lineage?position=${encodeURIComponent(row.position_id)}`} className="ml-auto text-xs text-blue-700 hover:underline">full lineage to the 6G file</a>
        <button onClick={onClose}><X className="w-4 h-4 text-slate-400" /></button></div>
      <table className="w-full text-xs bg-white rounded-lg border border-slate-200">
        <thead className="text-slate-500 bg-slate-50"><tr><th className="text-left px-3 py-1.5 w-56">FR 2052a field</th><th className="text-left w-48">Value</th><th className="text-left w-56">From (source)</th><th className="text-left">How it was derived</th></tr></thead>
        <tbody>{fields.map((f) => (
          <tr key={f.column} className="border-t border-slate-100 align-top">
            <td className="px-3 py-1.5">{f.label} <span className={`text-[9px] ${f.field_class === 'Mandatory' ? 'text-red-600' : 'text-slate-400'}`}>{f.field_class}</span></td>
            <td className="font-medium text-navy-900">{show(row[f.column]) || <span className="text-slate-300">(empty)</span>}</td>
            <td className="text-slate-600">{f.source === f.column ? 'the source record' : <><span className="font-mono">{f.source.replace(/_/g, ' ')}</span> = {show(row[f.source]) || '(empty)'}</>}</td>
            <td className="text-slate-600">{howOf(f, row)}</td></tr>))}</tbody>
      </table>
      <div className="text-xs bg-white rounded-lg border border-slate-200 p-3"><b>PID {row.product_id}</b> by rule <span className="font-mono">{row.pid_rule_id}</span>
        {row.pid_rule_condition && <> - the first rule (in priority order) whose condition matched: <span className="font-mono text-slate-700">{row.pid_rule_condition}</span></>}
        {row.pid_rule_rationale && <div className="text-slate-500 mt-0.5">{row.pid_rule_rationale}</div>}
        {row.issues && <div className="text-amber-800 mt-1">Missing: {row.issues}</div>}</div>
    </div>
  );
}

export default function Enrich({ date }) {
  const [tab, setTab] = useState('review');
  const [queue, setQueue] = useState([]);
  const [ready, setReady] = useState(false);
  const [params] = useSearchParams();
  const [sel, setSel] = useState(params.get('item'));
  const [filter, setFilter] = useState({ state: params.get('item') ? 'all' : 'open', q: '' });
  const [tables, setTables] = useState([]);
  const [sum, setSum] = useState({ tables: [], held_out: [] });
  const [code, setCode] = useState(null);
  const [pids, setPids] = useState([]);
  const [pid, setPid] = useState(null);
  const [pageData, setPageData] = useState(null);
  const [page, setPage] = useState(0);
  const [pos, setPos] = useState(null);
  const [run, setRun] = useState({});
  const [msg, setMsg] = useState('');
  const loadQ = useCallback(() => { if (date) api.wbEnrichQueue(date).then((q) => { setReady(true); setQueue(q.map((r) => ({ ...r, s: S[r.status] || 'review' }))); }).catch((e) => setMsg(e.message)); }, [date]);
  const loadRun = useCallback(() => { if (date) api.wbRerunStatus(date).then(setRun).catch(() => {}); }, [date]);
  useEffect(() => { api.getTables().then((t) => setTables(t.filter((x) => x.section !== 'Comments'))).catch(() => {}); }, []);
  useEffect(() => { if (date) { setSel((s) => (s === params.get('item') ? s : null)); setCode(null); setPid(null); setPos(null); loadQ(); loadRun(); api.wbEnrich(date).then(setSum).catch(() => {}); } }, [date, loadQ, loadRun]);
  useEffect(() => { if (date && code) { setPids([]); setPid(null); api.wbEnrichPids(date, code).then(setPids).catch(() => {}); } }, [date, code]);
  useEffect(() => { if (date && code && pid) { setPageData(null); api.wbEnrichPositions(date, code, pid, page).then(setPageData).catch(() => {}); } }, [date, code, pid, page]);
  useEffect(() => { if (!RUNNING.includes(run.state)) return undefined; const t = setInterval(loadRun, 15000); return () => clearInterval(t); }, [run.state, loadRun]);

  const counts = queueCounts(queue);
  const shown = useMemo(() => filterQueue(queue, filter, null), [queue, filter]);
  const item = queue.find((q) => q.id === sel) || shown[0];
  const next = () => { const i = shown.findIndex((q) => q.id === item?.id); const nx = shown[i + 1]; loadQ(); setSel(nx ? nx.id : null); };
  const st = (c) => sum.tables.find((x) => x.table_code === c) || {};
  const rerun = async () => { setMsg(''); try { const r = await api.wbRerunFromDq(date); setMsg(`Re-run started (job run ${r.run_id}).`); loadRun(); } catch (e) { setMsg(e.message); } };
  const totalPos = sum.tables.reduce((a, x) => a + parseInt(x.positions || 0), 0);

  return (
    <div className="space-y-4">
      <StepHeader n={3} date={date}>
        {totalPos} positions enriched from the customer and security masters and classified by the PID rules. Review what the AI flagged, then re-run the enrichment.
      </StepHeader>
      {msg && <div className="text-xs text-blue-700">{msg}</div>}
      <StepTabs tabs={[['review', `Needs review (${counts.open})`], ['browse', 'Browse enriched data']]} tab={tab} setTab={setTab}>
        <BulkApprove date={date} match={(b) => b.source_kind === 'ai' && b.break_type !== 'Comment for the Fed'} onDone={loadQ} />
        <Rerun run={run} label="Re-run enrichment" onClick={rerun} />
      </StepTabs>

      {tab === 'review' && !ready && <div className="text-sm text-slate-500">Loading...</div>}
      {tab === 'review' && ready && (queue.length === 0 ? <AllClear>Nothing to review: every position is enriched and classified.</AllClear> : (<>
        <QueueFilters filter={filter} setFilter={(f) => { setFilter(f); setSel(null); }} counts={counts} />
        {filter.state === 'open' && counts.open === 0
          ? <AllClear>Nothing left to review: {counts.done} decided - see Decided.</AllClear>
          : (
          <Queue items={shown} keyOf={(q) => q.id} sel={item?.id} setSel={setSel} noun="item" row={(q) => [q.kind, q.title, q.affects]}>
            {item && <ReviewItem date={date} item={item} onDone={next} />}
          </Queue>)}
      </>))}

      {tab === 'browse' && (
        <div className="grid grid-cols-5 gap-4">
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-2 text-xs self-start">
            {SECTIONS.map((sec) => (
              <div key={sec} className="mb-2">
                <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-slate-400">{sec}</div>
                {tables.filter((t) => t.section === sec).map((t) => (
                  <button key={t.table_code} onClick={() => { setCode(t.table_code); setPos(null); setPage(0); }}
                    className={`w-full text-left px-2 py-1 rounded flex items-center ${code === t.table_code ? 'bg-navy-900 text-white' : 'hover:bg-slate-50'}`}>
                    <span className="font-mono w-10">{t.table_code}</span><span className="flex-1 truncate">{t.table_name.replace(/^(Inflows|Outflows|Supplemental)-/, '')}</span>
                    <span className={code === t.table_code ? 'text-slate-300' : 'text-slate-400'}>{st(t.table_code).positions || 0}</span></button>))}
              </div>))}
          </div>
          <div className="col-span-4 space-y-3">
            {!code && <div className="text-sm text-slate-500 p-4">Pick a table on the left: Inflows, Outflows or Supplemental, as the Federal Reserve structures the report.</div>}
            {code && (
              <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
                <div className="px-4 py-2 border-b border-slate-100 text-sm font-semibold text-navy-900">{code} by product (PID)</div>
                <table className="w-full text-xs"><thead className="text-slate-400"><tr><th className="text-left px-4 py-1">PID</th><th className="text-left">Product</th><th className="text-right">Positions</th><th className="text-right">USD mm</th><th className="text-right">PID rules that fired</th><th className="text-right pr-4">Positions with a field missing</th></tr></thead>
                  <tbody>{pids.map((p) => (
                    <tr key={p.product_id} onClick={() => { setPid(p.product_id); setPage(0); setPos(null); }} className={`border-t border-slate-100 cursor-pointer ${pid === p.product_id ? 'bg-blue-50' : 'hover:bg-slate-50'}`}>
                      <td className="px-4 py-1.5 font-mono font-semibold">{p.product_id}</td><td>{p.product_name}</td><td className="text-right">{p.positions}</td><td className="text-right">{num(p.usd_mm, 0)}</td>
                      <td className="text-right">{p.rules}</td><td className={`text-right pr-4 ${parseInt(p.with_issues) ? 'text-amber-700 font-semibold' : 'text-slate-400'}`}>{p.with_issues}</td></tr>))}</tbody></table>
              </div>
            )}
            {pid && pageData && (
              <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
                <div className="px-4 py-2 border-b border-slate-100 text-xs flex items-center gap-2">
                  <b>{pid}</b> positions {pageData.total ? `${page * pageData.size + 1}-${Math.min((page + 1) * pageData.size, pageData.total)} of ${pageData.total}` : ''}
                  <span className="text-slate-400">- source values on the left, the FR 2052a fields of {code} (6G spec) on the right; click a position to see how each field was derived</span>
                  <span className="ml-auto flex gap-1"><button disabled={page === 0} onClick={() => setPage(page - 1)} className="p-1 rounded border border-slate-200 disabled:opacity-30"><ChevronLeft className="w-3.5 h-3.5" /></button>
                    <button disabled={(page + 1) * pageData.size >= pageData.total} onClick={() => setPage(page + 1)} className="p-1 rounded border border-slate-200 disabled:opacity-30"><ChevronRight className="w-3.5 h-3.5" /></button></span></div>
                <div className="overflow-x-auto">
                  <table className="text-[11px] whitespace-nowrap">
                    <thead><tr className="text-[10px] uppercase tracking-wider text-slate-400 bg-slate-50">
                      <th className="text-left px-3 py-1 sticky left-0 bg-slate-50" colSpan={1}>Position</th>
                      <th className="text-left px-2 border-l border-slate-200" colSpan={4}>Source record</th>
                      <th className="text-left px-2 border-l border-slate-200" colSpan={pageData.fields.length}>FR 2052a fields after enrichment</th>
                      <th className="text-left px-2 border-l border-slate-200" colSpan={2}>Result</th></tr>
                      <tr className="text-slate-500">
                        <th className="text-left px-3 py-1 sticky left-0 bg-white" />
                        {['System', 'Bank product code', 'Customer', 'Collateral'].map((h, i) => <th key={h} className={`text-left px-2 py-1 ${i === 0 ? 'border-l border-slate-200' : ''}`}>{h}</th>)}
                        {pageData.fields.map((f, i) => <th key={f.column} className={`text-left px-2 py-1 ${i === 0 ? 'border-l border-slate-200' : ''}`}>{f.label}
                          <div className={`text-[9px] font-normal ${f.field_class === 'Mandatory' ? 'text-red-600' : 'text-slate-400'}`}>{f.field_class}</div></th>)}
                        <th className="text-left px-2 py-1 border-l border-slate-200">PID rule</th><th className="text-left px-2 py-1">Missing</th></tr></thead>
                    <tbody>{pageData.rows.map((r) => (
                      <tr key={r.position_id} onClick={() => setPos(pos === r.position_id ? null : r.position_id)} className={`border-t border-slate-100 cursor-pointer ${pos === r.position_id ? 'bg-blue-50' : 'hover:bg-slate-50'}`}>
                        <td className={`px-3 py-1 font-mono sticky left-0 ${pos === r.position_id ? 'bg-blue-50' : 'bg-white'}`}>{r.position_id}</td>
                        <td className="px-2 border-l border-slate-100">{r.source_system}</td><td className="px-2 font-mono">{r.source_product_code}</td>
                        <td className="px-2 font-mono">{r.customer_id || ''}</td><td className="px-2 font-mono">{r.collateral_id || ''}</td>
                        {pageData.fields.map((f, i) => <td key={f.column} className={`px-2 ${i === 0 ? 'border-l border-slate-100' : ''}`}>{show(r[f.column])}</td>)}
                        <td className="px-2 font-mono border-l border-slate-100">{r.pid_rule_id}</td><td className="px-2 text-amber-800">{r.issues}</td></tr>))}</tbody>
                  </table>
                </div>
                {pos && <HowEnriched row={pageData.rows.find((r) => r.position_id === pos)} fields={pageData.fields} onClose={() => setPos(null)} />}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

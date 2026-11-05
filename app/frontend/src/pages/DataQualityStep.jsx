import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api';
import StepHeader from '../components/StepHeader';
import AgentEvidence, { BulkApprove } from '../components/AgentEvidence';
import { StepTabs, Rerun, QueueFilters, Queue, Detail, AiFix, Actions, Btn, Decided, AllClear, filterQueue, queueCounts, isDecided, RUNNING } from '../components/StepKit';
import { Check, PencilLine, Ban } from 'lucide-react';

const SKIP = new Set(['record_id', 'as_of_date', 'load_timestamp', 'source_feed']);

// One failing record: what rule it broke, the AI-suggested fix, the agent's evidence, then accept / fix manually / exclude.
function Resolve({ date, item, onDone }) {
  const [rec, setRec] = useState(null);
  const [ai, setAi] = useState(null);
  const [mode, setMode] = useState(null);
  const [edits, setEdits] = useState({});
  const [reason, setReason] = useState('');
  const [msg, setMsg] = useState('');
  useEffect(() => {
    setRec(null); setAi(null); setMode(null); setEdits({}); setReason(''); setMsg('');
    api.wbCollectRecord(date, item.record_id).then(setRec).catch((e) => setMsg(e.message));
    if (item.quarantined !== '0') api.wbDqSuggest(date, item.record_id).then(setAi).catch(() => setAi({ rationale: 'No AI suggestion available.' }));
  }, [date, item.record_id, item.quarantined]);
  const act = async (action, extra = {}) => {
    setMsg('');
    try { await api.wbDqResolve(date, { record_id: item.record_id, action, reason, ...extra }); onDone(); }
    catch (e) { setMsg(e.message); }
  };
  const acceptAi = () => (ai.action === 'exclude' ? act('exclude', { reason: reason || ai.rationale })
    : ai.action === 'map_code' ? act('map_code', { new_value: ai.new_value, reason: reason || ai.rationale })
      : act('accept_ai', { edits: { [ai.field]: ai.new_value }, reason: reason || ai.rationale }));
  const values = rec?.values || {};
  const broken = new Set((ai?.field ? [ai.field] : []));
  const fix = !ai?.action ? 'No suggestion' : ai.action === 'fix_field'
    ? <>Set <span className="font-mono">{ai.field}</span> from <span className="font-mono line-through text-slate-500">{String(values[ai.field] ?? '(empty)')}</span> to <span className="font-mono">{String(ai.new_value)}</span></>
    : ai.action === 'map_code' ? <>Map the new product code <span className="font-mono">{values.source_product_code}</span> to standard product type <span className="font-mono">{ai.new_value}</span></>
      : 'Exclude the record from the report';

  return (
    <Detail tag={item.source_feed} title={item.record_id} s={item.s}
      sub={`${item.source_system} | ${item.source_product_code}${rec?.source ? ` | received in ${rec.source.landing_file?.split('/').slice(-2).join('/')}` : ''}`}>
      {(rec?.failed_rules || []).map((f) => (
        <div key={f.rule_id} className="text-sm"><span className="font-mono text-red-700 font-semibold">{f.rule_id}</span> <b>{f.rule_name}</b>
          <div className="text-xs text-slate-600">{f.rule_description}</div></div>))}
      {rec && !rec.failed_rules.length && rec.quarantine_reason && <div className="text-sm"><b>{rec.quarantine_reason}</b></div>}
      {item.s === 'warning' && <Decided>A WARNING rule: the record passed and is already in Silver. Nothing to resolve here.</Decided>}
      {isDecided(item.s) && item.decision && (
        <Decided>Decided by {item.decision.preparer}: {item.decision.field === '_exclude' ? 'excluded' : item.decision.field === '_map_code' ? `product code mapped to ${item.decision.new_value}` : `${item.decision.field} -> ${item.decision.new_value}`} ({item.decision.reason}).
          {item.s === 'rerun' && ' Re-run from data quality to put the record back.'} You can change the decision below.</Decided>)}
      {item.s !== 'warning' && <>
        <AiFix confidence={ai?.confidence} loading={!ai} title={fix} rationale={ai?.rationale} />
        <Actions>
          <Btn primary icon={Check} disabled={!ai?.action} onClick={acceptAi}>Accept AI fix</Btn>
          <Btn icon={PencilLine} active={mode === 'manual'} onClick={() => setMode(mode === 'manual' ? null : 'manual')}>Fix manually</Btn>
          <Btn icon={Ban} active={mode === 'exclude'} onClick={() => setMode(mode === 'exclude' ? null : 'exclude')}>Exclude</Btn>
        </Actions>
      </>}
      {mode === 'manual' && rec && (
        <div className="space-y-2">
          <div className="grid grid-cols-3 gap-2">
            {Object.entries(values).filter(([k]) => !SKIP.has(k)).map(([k, v]) => (
              <label key={k} className="text-[11px]"><span className={broken.has(k) ? 'text-red-700 font-semibold' : 'text-slate-400'}>{k.replace(/_/g, ' ')}</span>
                <input defaultValue={v ?? ''} onChange={(e) => setEdits((x) => { const n = { ...x }; if (e.target.value === String(v ?? '')) delete n[k]; else n[k] = e.target.value; return n; })}
                  className={`w-full border rounded px-1.5 py-1 ${edits[k] !== undefined ? 'border-blue-500 bg-blue-50' : broken.has(k) ? 'border-red-300' : 'border-slate-200'}`} /></label>))}
          </div>
          <div className="flex gap-2"><input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (required)" className="flex-1 border border-slate-200 rounded px-2 py-1.5 text-xs" />
            <button disabled={!Object.keys(edits).length || !reason.trim()} onClick={() => act('manual', { edits })} className="px-4 py-1.5 rounded-lg text-xs font-medium bg-blue-600 text-white disabled:opacity-40">Save fix</button></div>
        </div>)}
      {mode === 'exclude' && (
        <div className="flex gap-2"><input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why it stays out of the report (required)" className="flex-1 border border-slate-200 rounded px-2 py-1.5 text-xs" />
          <button disabled={!reason.trim()} onClick={() => act('exclude')} className="px-4 py-1.5 rounded-lg text-xs font-medium bg-slate-700 text-white disabled:opacity-40">Exclude</button></div>)}
      {item.s !== 'warning' && <AgentEvidence date={date} kind="dq" refKey={item.record_id} />}
      {msg && <div className="text-xs text-red-600">{msg}</div>}
      {rec && mode !== 'manual' && (
        <details className="text-[11px]"><summary className="text-slate-500 cursor-pointer">The record as received ({Object.keys(values).length} fields) and the rule SQL</summary>
          <div className="grid grid-cols-3 gap-x-4 gap-y-0.5 mt-2">{Object.entries(values).filter(([k, v]) => !SKIP.has(k) && v != null && v !== '').map(([k, v]) => (
            <div key={k}><span className="text-slate-400">{k.replace(/_/g, ' ')}: </span>{String(v)}</div>))}</div>
          {(rec.failed_rules || []).map((f) => <div key={f.rule_id} className="font-mono text-[10px] text-slate-500 mt-2 break-all">{f.rule_id} fails when: {f.fail_predicate}</div>)}
        </details>)}
    </Detail>
  );
}

// Step 2: Needs review = the records that failed a data quality rule (AI fix, manual fix or exclude), then re-run from data quality
// to put the fixed records back into Silver; Browse rules = every data quality rule and how many records it failed today.
const S = { open: 'review', 'fix pending re-run': 'rerun', mapped: 'rerun', fixed: 'done', excluded: 'excluded', warning: 'warning' };
export default function DataQualityStep({ date }) {
  const [params] = useSearchParams();
  const [tab, setTab] = useState('review');
  const [queue, setQueue] = useState([]);
  const [ready, setReady] = useState(false);
  const [rules, setRules] = useState([]);
  const [sel, setSel] = useState(params.get('item'));
  const [filter, setFilter] = useState({ state: params.get('item') ? 'all' : 'open', rule: '', q: '' });
  const [run, setRun] = useState({});
  const [msg, setMsg] = useState('');
  const load = useCallback(() => { if (date) api.wbDqQueue(date).then((q) => { setReady(true); setQueue(q.map((r) => ({ ...r, s: S[r.state] || 'review' }))); }).catch((e) => setMsg(e.message)); }, [date]);
  const loadRun = useCallback(() => { if (date) api.wbRerunStatus(date).then(setRun).catch(() => {}); }, [date]);
  useEffect(() => { if (date) { setSel((s) => (s === params.get('item') ? s : null)); load(); loadRun(); api.wbCollect(date).then((d) => setRules(d.rules)).catch(() => {}); } }, [date, load, loadRun]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!RUNNING.includes(run.state)) return undefined; const t = setInterval(loadRun, 15000); return () => clearInterval(t); }, [run.state, loadRun]);

  const shown = useMemo(() => filterQueue(queue, filter, null).filter((r) => !filter.rule || r.rules.split(', ').includes(filter.rule)), [queue, filter]);
  const item = queue.find((r) => r.record_id === sel) || shown[0];
  const counts = queueCounts(queue);
  const failedRules = rules.filter((r) => r.failed_records && r.failed_records !== '0');
  const next = () => { load(); const i = shown.findIndex((r) => r.record_id === item?.record_id); const nx = shown[i + 1] || shown[i - 1]; setSel(nx ? nx.record_id : null); };
  const rerun = async () => { setMsg(''); try { const r = await api.wbRerunFromDq(date); setMsg(`Re-run started (job run ${r.run_id}); about 20 minutes.`); loadRun(); } catch (e) { setMsg(e.message); } };

  return (
    <div className="space-y-4">
      <StepHeader n={2} date={date}>
        {rules.length} rules ({rules.length - failedRules.length} passed, {failedRules.length} failed). Records that pass move to Silver; records failing an ERROR
        rule are held back. Review each one, then re-run from data quality.
      </StepHeader>
      {msg && <div className="text-xs text-blue-700">{msg}</div>}
      <StepTabs tabs={[['review', `Needs review (${counts.open})`], ['rules', 'Browse data quality rules']]} tab={tab} setTab={setTab}>
        <BulkApprove date={date} match={(b) => b.source_kind === 'dq'} onDone={load} />
        <Rerun run={run} label="Re-run from data quality" onClick={rerun} />
      </StepTabs>

      {tab === 'review' && !ready && <div className="text-sm text-slate-500">Loading...</div>}
      {tab === 'review' && ready && (queue.length === 0 ? <AllClear>Nothing to review: every record passed every data quality rule.</AllClear> : (<>
        <QueueFilters filter={filter} setFilter={(f) => { setFilter(f); setSel(null); }} counts={counts}
          rules={failedRules.map((r) => [r.rule_id, `${r.rule_id} ${r.rule_name} (${r.failed_records})`])} />
        {filter.state === 'open' && counts.open === 0
          ? <AllClear>Nothing left to review: {counts.done} decided - see Decided.</AllClear>
          : (
          <Queue items={shown} keyOf={(r) => r.record_id} sel={item?.record_id} setSel={setSel} noun="record"
            row={(r) => [r.source_feed, r.record_id, `${r.rule_names} | ${r.source_product_code} | customer ${r.customer_id || '-'} | ${r.amount} ${r.currency}`]}>
            {item ? <Resolve date={date} item={item} onDone={next} /> : <div className="text-sm text-slate-500 p-4">Pick a record.</div>}
          </Queue>)}
      </>))}

      {tab === 'rules' && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
          <table className="w-full text-xs">
            <thead className="text-slate-500 bg-slate-50"><tr><th className="text-left px-4 py-2">Rule</th><th className="text-left">What it checks</th><th className="text-left">Severity</th>
              <th className="text-right">Records failed</th><th className="text-right pr-4">Result</th></tr></thead>
            <tbody>{rules.map((r) => {
              const failed = parseInt(r.failed_records || 0);
              return (
                <tr key={r.rule_id} className="border-t border-slate-100">
                  <td className="px-4 py-2 font-mono font-semibold">{r.rule_id}</td><td>{r.rule_name}<div className="text-[11px] text-slate-400">{r.rule_description}</div></td>
                  <td>{r.severity}</td><td className="text-right">{failed}</td>
                  <td className={`text-right pr-4 font-semibold ${failed ? (r.severity === 'ERROR' ? 'text-red-700' : 'text-amber-700') : 'text-emerald-700'}`}>{failed ? (r.severity === 'ERROR' ? 'FAIL' : 'WARNING') : 'PASS'}</td>
                </tr>);
            })}</tbody>
          </table>
        </div>)}
    </div>
  );
}

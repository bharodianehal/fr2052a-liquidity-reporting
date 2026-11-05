import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import StepHeader from '../components/StepHeader';
import AgentEvidence, { BulkApprove } from '../components/AgentEvidence';
import ReportTables from './ReportTables';
import CommentItem, { TYPE, COMMENT_STATE, sug } from '../components/CommentItem';
import { StepTabs, Rerun, QueueFilters, Queue, Detail, AiFix, Actions, Btn, Decided, AllClear, filterQueue, queueCounts, RUNNING } from '../components/StepKit';
import { PencilLine, X, Check, MessageSquareText } from 'lucide-react';

const SOURCE = { 'Fed PSV': 'Fed post-submission check', '6G BR': 'Fed 6G business rule', '6G BR General': 'Fed 6G file rule', '6G XSD': 'Fed 6G schema', Instructions: 'FR 2052a Instructions' };
const S = { open: 'review', 'corrected - re-run': 'rerun', corrected: 'done', explained: 'explained' };

export function Corrector({ date, target, onClose, onSaved }) {
  const [d, setD] = useState(null);
  const [edits, setEdits] = useState({});
  const [reason, setReason] = useState('');
  const [msg, setMsg] = useState('');
  useEffect(() => { setD(null); setEdits({}); api.wbCorrectTarget(date, target).then(setD).catch((e) => setMsg(e.message)); }, [date, target]);
  const changes = Object.entries(edits).flatMap(([pid, f]) => Object.entries(f).map(([field, v]) => ({ pid, field, v })));
  const save = async () => {
    setMsg('');
    try {
      for (const c of changes) await api.wbPostCorrection(date, { position_id: c.pid, field: c.field, new_value: c.v, reason, record_key: target.record_key });
      setMsg(`${changes.length} correction(s) saved - re-run the validation to apply them.`); setEdits({}); onSaved();
    } catch (e) { setMsg(e.message); }
  };
  return (
    <div className="bg-white rounded-xl border-2 border-blue-300 shadow-md">
      <div className="px-4 py-2.5 border-b border-slate-100 flex items-center gap-2">
        <PencilLine className="w-4 h-4 text-blue-600" />
        <span className="text-sm font-semibold text-navy-900">Correct the positions{d ? ` - ${d.table_code}, ${d.positions.length} position(s)` : ''}</span>
        <span className="text-[11px] text-slate-500">the most granular data held: each position of the record; change a field, give the reason, save</span>
        {target.record_key && <Link to={`/lineage?key=${target.record_key}`} className="ml-auto text-xs text-blue-700 hover:underline">trace</Link>}
        <button onClick={onClose} className={target.record_key ? '' : 'ml-auto'}><X className="w-4 h-4 text-slate-400" /></button>
      </div>
      {!d && <div className="p-4 text-xs text-slate-500">{msg || 'Loading the positions...'}</div>}
      {d && (
        <div className="p-3 space-y-3">
          <div className="overflow-x-auto">
            <table className="text-[11px]">
              <thead className="bg-slate-50"><tr>
                <th className="text-left px-2 py-1 sticky left-0 bg-slate-50">Position</th>
                {d.fields.map((f) => <th key={f.column} className="text-left px-2 py-1 whitespace-nowrap">{f.label}
                  <div className={`text-[9px] font-normal ${f.field_class === 'Mandatory' ? 'text-red-600' : 'text-slate-400'}`}>{f.field_class}</div></th>)}
              </tr></thead>
              <tbody>{d.positions.map((p) => (
                <tr key={p.position_id} className="border-t border-slate-100">
                  <td className="px-2 py-1 font-mono sticky left-0 bg-white whitespace-nowrap">{p.position_id}<div className="text-[9px] text-slate-400">{p.source_system} {p.source_product_code} @ {p.booking_entity}</div></td>
                  {d.fields.map((f) => {
                    const changed = edits[p.position_id]?.[f.column] !== undefined;
                    return (
                      <td key={f.column} className="px-1 py-1">
                        <input defaultValue={p[f.column] ?? ''} onChange={(e) => {
                          const v = e.target.value; const orig = p[f.column] ?? '';
                          setEdits((x) => { const n = { ...x, [p.position_id]: { ...(x[p.position_id] || {}) } }; if (v === String(orig)) delete n[p.position_id][f.column]; else n[p.position_id][f.column] = v; return n; });
                        }} className={`w-28 border rounded px-1 py-0.5 ${changed ? 'border-blue-500 bg-blue-50' : 'border-slate-200'}`} />
                      </td>
                    );
                  })}
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div className="flex gap-2 items-center">
            <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason for the correction (required)" className="flex-1 border border-slate-200 rounded px-2 py-1 text-xs" />
            <button disabled={!changes.length || !reason.trim()} onClick={save} className="px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600 text-white disabled:opacity-40">
              Save {changes.length || ''} correction{changes.length === 1 ? '' : 's'}</button>
          </div>
          {msg && <div className="text-xs text-blue-700">{msg}</div>}
          {d.corrections.length > 0 && <div className="text-[11px] text-slate-500">Earlier corrections of these positions: {d.corrections.map((c) => `${c.position_id}.${c.field} ${c.old_value ?? ''} -> ${c.new_value ?? ''} (${c.status.toLowerCase()})`).join('; ')}</div>}
        </div>
      )}
    </div>
  );
}

// One exception: the rule, why this record failed, the AI fix, and accept / fix manually / explain & keep.
// One exception: the rule and what failed, the AI-suggested fix, the agent's evidence, then accept / fix manually / explain & keep.
function ResolveException({ date, item, onDone }) {
  const [ai, setAi] = useState(null);
  const [mode, setMode] = useState(null);
  const [note, setNote] = useState('');
  const [msg, setMsg] = useState('');
  const hasRecord = !!(item.record_key || item.position_id);
  useEffect(() => { setAi(null); setMode(null); setNote(''); setMsg('');
    api.wbValSuggest(date, item.rule_id, item.item_key).then(setAi).catch(() => setAi({ explanation: 'No AI suggestion available.' })); }, [date, item.rule_id, item.item_key]);
  const act = async (action, extra = {}) => {
    setMsg('');
    try { await api.wbValResolve(date, { rule_id: item.rule_id, item_key: item.item_key, record_key: item.record_key, action, note, ...extra }); onDone(); }
    catch (e) { setMsg(e.message); }
  };
  const acceptAi = () => (ai.action === 'correct' ? act('accept_ai', { position_id: ai.position_id, field: ai.field, new_value: ai.new_value, note: note || ai.explanation })
    : act('explain', { note: note || ai.explanation }));
  const fix = !ai?.action ? 'No suggestion' : ai.action === 'correct'
    ? <>Correct <span className="font-mono">{ai.position_id}</span>: <span className="font-mono">{ai.field}</span> <span className="line-through text-slate-500 font-mono">{String(ai.old_value ?? '(empty)')}</span> to <span className="font-mono">{String(ai.new_value)}</span></>
    : 'Keep the data and record this explanation';
  return (
    <Detail tag={item.status === 'FAIL' ? 'FAIL' : 'WARNING'} title={`${item.rule_id} ${item.rule_name}`} s={item.s}
      sub={`${SOURCE[item.rule_source] || item.rule_source} | ${item.severity === 'ERROR' ? 'blocks the filing' : 'warning - explain or fix'} | table ${item.table_code} ${item.product_id || ''}`}>
      <div className="text-sm text-slate-800">{item.detail}</div>
      {item.decision && <Decided>{item.decision.action === 'explain' ? 'Explained' : 'Corrected'} by {item.decision.decided_by}: {item.decision.note}</Decided>}
      <AiFix confidence={ai?.confidence} loading={!ai} title={fix} rationale={ai?.explanation} />
      <Actions>
        <Btn primary icon={Check} disabled={!ai?.action} onClick={acceptAi}>Accept AI fix</Btn>
        {hasRecord && <Btn icon={PencilLine} active={mode === 'manual'} onClick={() => setMode(mode === 'manual' ? null : 'manual')}>Fix manually</Btn>}
        {item.severity !== 'ERROR' && <Btn icon={MessageSquareText} active={mode === 'explain'} onClick={() => setMode(mode === 'explain' ? null : 'explain')}>Explain & keep</Btn>}
      </Actions>
      {mode === 'manual' && <Corrector date={date} target={item.record_key ? { record_key: item.record_key } : { position_id: item.position_id }} onClose={() => setMode(null)}
        onSaved={() => act('manual', { note: 'Manual correction of the positions' })} />}
      {mode === 'explain' && (
        <div className="flex gap-2"><input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Explanation kept with the filing (required)" className="flex-1 border border-slate-200 rounded px-2 py-1.5 text-xs" />
          <button disabled={!note.trim()} onClick={() => act('explain')} className="px-4 py-1.5 rounded-lg text-xs font-medium bg-slate-700 text-white disabled:opacity-40">Save explanation</button></div>)}
      <AgentEvidence date={date} kind="validate" refKey={`${item.rule_id}|${item.item_key}`.slice(0, 400)} />
      {msg && <div className="text-xs text-red-600">{msg}</div>}
      {item.record_key && <Link to={`/lineage?key=${item.record_key}`} className="text-xs text-blue-700 hover:underline">trace this record to its source</Link>}
    </Detail>
  );
}

// Step 4: Needs review = every exception of the Instructions rules, the Fed 6G business rules, the Fed post-submission checks and the
// reconciliations (AI fix, manual fix, explain a warning), then re-run the validation; Browse report tables = the report as filed.
export default function Validate({ date }) {
  const [params] = useSearchParams();
  const [tab, setTab] = useState('review');
  const [queue, setQueue] = useState([]);
  const [ready, setReady] = useState(false);
  const [checks, setChecks] = useState([]);
  const [sel, setSel] = useState(params.get('item'));
  const [filter, setFilter] = useState({ state: params.get('item') ? 'all' : 'open', rule: '', q: '' });
  const [run, setRun] = useState({});
  const [msg, setMsg] = useState('');
  // one queue: the exceptions of the checks, then the comments the AI drafted for the Fed (they go into the 6G Comment file)
  const load = useCallback(() => {
    if (!date) return;
    Promise.all([api.wbValQueue(date), api.wbAi(date)]).then(([q, ai]) => {
      setReady(true);
      setQueue([...q.map((r) => ({ ...r, s: S[r.state] || 'review', _k: `${r.rule_id}|${r.item_key}` })),
        ...ai.filter((c) => TYPE[c.suggestion_type]).map((c) => ({ ...c, s: COMMENT_STATE[c.status] || 'review', _k: `c|${c.suggestion_id}`, _comment: true }))]);
    }).catch((e) => setMsg(e.message));
  }, [date]);
  const loadRun = useCallback(() => { if (date) api.wbRevalidateStatus(date).then(setRun).catch(() => {}); }, [date]);
  useEffect(() => { if (date) { setSel((s) => (s === params.get('item') ? s : null)); load(); loadRun(); api.getValidation(date).then(setChecks).catch(() => {}); } }, [date, load, loadRun]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!RUNNING.includes(run.state)) return undefined; const t = setInterval(loadRun, 15000); return () => clearInterval(t); }, [run.state, loadRun]);
  const key = (r) => r._k;
  const shown = useMemo(() => filterQueue(queue, filter, (r) => (r._comment ? 'COMMENT' : r.rule_id)), [queue, filter]);
  const item = queue.find((r) => key(r) === sel) || shown[0];
  const rulesBad = [...new Map(queue.filter((r) => !r._comment).map((r) => [r.rule_id, r])).values()];
  const nComments = queue.filter((r) => r._comment).length;
  const total = checks.reduce((a, c) => ({ ...a, [c.status]: (a[c.status] || 0) + 1 }), {});
  const counts = queueCounts(queue);
  const next = () => { const i = shown.findIndex((r) => r === item); const nx = shown[i + 1]; load(); setSel(nx ? key(nx) : null); };
  const rerun = async () => { setMsg(''); try { const r = await api.wbRevalidate(date); setMsg(`Re-validation started (job run ${r.run_id}); about 10 minutes.`); loadRun(); } catch (e) { setMsg(e.message); } };

  return (
    <div className="space-y-4">
      <StepHeader n={4} date={date}>
        {checks.length} checks: {total.PASS || 0} passed, {total.FAIL || 0} failed, {total.WARNING || 0} warnings. Review each exception and each comment the AI drafted for the Fed, then re-run the validation until none is left.
      </StepHeader>
      {msg && <div className="text-xs text-blue-700">{msg}</div>}
      <StepTabs tabs={[['review', `Needs review (${counts.open})`], ['tables', 'Browse report tables']]} tab={tab} setTab={setTab}>
        <BulkApprove date={date} match={(b) => b.source_kind === 'validate' || b.break_type === 'Comment for the Fed'} onDone={load} />
        <Rerun run={run} label="Re-run validation" onClick={rerun} />
      </StepTabs>

      {tab === 'tables' && <ReportTables date={date} embedded />}
      {tab === 'review' && !ready && <div className="text-sm text-slate-500">Loading...</div>}
      {tab === 'review' && ready && (queue.length === 0 ? <AllClear>Nothing to review: every check passes. Go to Generate 6G & release.</AllClear> : (<>
        <QueueFilters filter={filter} setFilter={(f) => { setFilter(f); setSel(null); }} counts={counts}
          rules={[...rulesBad.map((r) => [r.rule_id, `${r.rule_id} ${r.rule_name} (${queue.filter((x) => !x._comment && x.rule_id === r.rule_id).length})`]),
            ...(nComments ? [['COMMENT', `Comments for the Fed (${nComments})`]] : [])]} />
        {filter.state === 'open' && counts.open === 0
          ? <AllClear>Nothing left to review: {counts.done} decided - see Decided.</AllClear>
          : (
          <Queue items={shown} keyOf={key} sel={item ? key(item) : null} setSel={setSel} noun="item"
            row={(r) => (r._comment ? [TYPE[r.suggestion_type][0], r.subject, String(sug(r)[TYPE[r.suggestion_type][1]] || '').slice(0, 120)]
            : [r.status === 'FAIL' ? 'FAIL' : 'WARN', `${r.rule_id} ${r.rule_name}`, `${r.table_code} ${r.product_id || ''} | ${r.position_id || r.detail}`])}>
            {item && (item._comment ? <CommentItem date={date} item={item} onDone={next} /> : <ResolveException date={date} item={item} onDone={next} />)}
          </Queue>)}
      </>))}
    </div>
  );
}

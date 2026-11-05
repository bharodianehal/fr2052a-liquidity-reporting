import React, { useState, useEffect, useCallback } from 'react';
import { Navigate, useParams } from 'react-router-dom';
import { api } from '../api';
import { BookOpen, ShieldCheck, Zap, Wrench, MessageSquare, Undo2, RotateCcw, X, CircleCheck, TriangleAlert, ChevronDown, ChevronRight, CheckCheck } from 'lucide-react';

const num = (v, d = 1) => (v == null || v === '' ? '' : parseFloat(v).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d }));

export const Status = ({ s }) => {
  const c = { PROPOSED: 'bg-blue-50 text-blue-700', APPROVED: 'bg-emerald-50 text-emerald-700', RETURNED: 'bg-amber-50 text-amber-700' }[s] || 'bg-slate-100 text-slate-600';
  return <span className={`text-[10px] px-1.5 py-0.5 rounded whitespace-nowrap ${c}`}>{s === 'PROPOSED' ? 'waiting for you' : String(s || '').toLowerCase()}</span>;
};

// Where a break is decided: the step page that owns its item (the only place to act on it).
export function stepLink(b) {
  const ref = encodeURIComponent(b.source_ref || '');
  if (b.source_kind === 'dq') return `/dq?item=${ref}`;
  if (b.source_kind === 'validate') return `/validate?item=${ref}`;
  if (b.source_kind === 'feed') return '/collect';
  if (b.break_type === 'Comment for the Fed') return `/validate?item=${encodeURIComponent(`c|${b.source_ref}`)}`;
  return `/enrich?item=${ref}`;
}

// Old links to a break (audit trail) open the item on its step page.
export function BreakRedirect() {
  const { id } = useParams();
  const [to, setTo] = useState(null);
  useEffect(() => { api.agBreak(id).then((d) => setTo(stepLink(d.break))).catch(() => setTo('/')); }, [id]);
  return to ? <Navigate to={to} replace /> : <div className="text-sm text-slate-500">Opening the step...</div>;
}

// Bulk approval on a step queue: only the agent proposals at 95% confidence or more, with the rule agent agreeing and no material LCR effect.
export function BulkApprove({ date, match, onDone }) {
  const [ids, setIds] = useState([]);
  const [msg, setMsg] = useState('');
  const load = useCallback(() => { if (date) api.agBreaks(date).then((b) => setIds(b.filter((x) => x.status === 'PROPOSED' && x.bulk_ok && match(x)).map((x) => x.break_id))).catch(() => {}); }, [date]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);
  if (!ids.length) return msg ? <span className="text-xs text-emerald-700">{msg}</span> : null;
  const go = async () => {
    setMsg('');
    try { const r = await api.agBulk(date, { break_ids: ids, reason_code: 'RC-01', note: 'Bulk approval: high confidence, rule agent agrees, no material LCR effect' });
      setMsg(`${r.approved} approved`); load(); onDone?.(); } catch (e) { setMsg(e.message); }
  };
  return (
    <button onClick={go} title="Only proposals at 95% confidence or more, with the rule agent agreeing and no material LCR effect"
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-emerald-300 text-emerald-800 hover:bg-emerald-50">
      <CheckCheck className="w-3.5 h-3.5" />Approve {ids.length} high-confidence</button>
  );
}

const Section = ({ icon: I, title, right, children, open: start = false }) => {
  const [open, setOpen] = useState(start);
  return (
    <div className="border-t border-slate-100">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-2 px-3 py-2 text-xs text-navy-900 hover:bg-slate-50">
        {open ? <ChevronDown className="w-3.5 h-3.5 text-slate-400" /> : <ChevronRight className="w-3.5 h-3.5 text-slate-400" />}<I className="w-3.5 h-3.5 text-slate-500" />
        <span className="font-semibold">{title}</span>{right && <span className="ml-auto text-[11px] text-slate-500">{right}</span>}</button>
      {open && <div className="px-3 pb-3">{children}</div>}
    </div>
  );
};

const SUGGEST = {
  'Data quality break': ['Why this value and not another?', 'What happens if I exclude the record instead?', 'Which FR 2052a product does the record end up in?'],
  'New customer': ['Why this counterparty type?', 'Which positions are held out and why?', 'What does the Instructions say about this counterparty?'],
  'New product code': ['Why this standard product type?', 'Which FR 2052a product will the records get?', 'What if the code is a typo of an existing one?'],
  'Validation warning': ['Why is this a warning and not a failure?', 'What does the Instructions say about this?', 'What happens to the LCR?'],
  'GL tie-out': ['What could explain the difference?', 'Which table and products are affected?', 'Does it block the filing?'],
  'Comment for the Fed': ['Is the FR 2052a table named correctly?', 'What does the Instructions say about comments?', 'Which numbers does the comment rely on?'],
};

function Ask({ b, onOpen }) {
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState([]);
  const go = async (question) => {
    if (!question.trim()) return;
    setBusy(true);
    try { const r = await api.agAsk(b.break_id, question); setLog((l) => [...l, { q: question, ...r }]); setQ(''); }
    catch (e) { setLog((l) => [...l, { q: question, answer: e.message, sources: [] }]); }
    setBusy(false);
  };
  return (
    <div className="space-y-2">
      {log.map((x, i) => (
        <div key={i}><div className="text-xs font-semibold text-navy-900">{x.q}</div>
          <div className="text-xs text-slate-700 bg-slate-50 rounded p-2">{x.answer}
            {(x.sources || []).length > 0 && <div className="mt-1 flex flex-wrap gap-1">{x.sources.map((s) => (
              <button key={s.n} onClick={() => onOpen(s)} className="px-1.5 rounded bg-blue-100 text-blue-700 text-[10px]">[{s.n}] {s.title.slice(0, 50)}</button>))}</div>}</div></div>))}
      <div className="flex flex-wrap gap-1">{(SUGGEST[b.break_type] || []).map((s) => <button key={s} disabled={busy} onClick={() => go(s)} className="px-2 py-0.5 rounded-full border border-blue-200 text-blue-700 text-[11px] hover:bg-blue-50">{s}</button>)}</div>
      <div className="flex gap-2"><input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && go(q)} placeholder="Ask about this item"
        className="flex-1 border border-slate-200 rounded px-2 py-1.5 text-xs" />
        <button disabled={busy || !q.trim()} onClick={() => go(q)} className="px-3 py-1.5 rounded-lg text-xs font-medium bg-navy-900 text-white disabled:opacity-40">{busy ? 'Thinking...' : 'Ask'}</button></div>
    </div>
  );
}

// The AI agent's evidence for one item of a step queue - shown on the step page, under the AI-suggested fix, where the checker decides:
// the independent rule check, the exact liquidity effect, the sources it read, how it got there, the source fix and "ask about it".
// Accepting is the step's own button; returning sends the proposal back to the agent with a reason.
export default function AgentEvidence({ date, kind, refKey, onChange }) {
  const [d, setD] = useState(null);
  const [passage, setPassage] = useState(null);
  const [ret, setRet] = useState(false);
  const [code, setCode] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const load = useCallback(() => { if (date && refKey) api.agItem(date, kind, refKey).then(setD).catch(() => setD({})); }, [date, kind, refKey]);
  useEffect(() => { setD(null); setRet(false); setCode(''); setNote(''); setMsg(''); load(); }, [load]);
  const p = d?.proposal;
  if (!d || !d.break || !p || (p.rule_check || {}).detail === 'Decided on the step page') return null;
  const b = d.break;
  const rc = p.rule_check || {};
  const imp = p.impact || {};
  const disagrees = rc.status === 'break';
  const sendBack = async () => {
    setBusy(true); setMsg('');
    try { await api.agDecide(b.break_id, { action: 'return', reason_code: code, note }); setRet(false); load(); onChange?.(); } catch (e) { setMsg(e.message); }
    setBusy(false);
  };
  const again = async () => { setBusy(true); setMsg(''); try { await api.agRerun(b.break_id); load(); onChange?.(); } catch (e) { setMsg(e.message); } setBusy(false); };
  const decs = d.decisions || [];
  const stp = decs.find((x) => x.reason_code === 'STP');
  const spot = decs.find((x) => String(x.action).startsWith('SPOT_CHECK'));
  const spotCheck = async (verdict) => {
    setBusy(true); setMsg('');
    try { const r = await api.agSpotCheck(b.break_id, verdict, note); setMsg(r.next || ''); setNote(''); load(); onChange?.(); } catch (e) { setMsg(e.message); }
    setBusy(false);
  };
  return (
    <div className="rounded-lg border border-slate-200">
      <div className={`px-3 py-2 text-xs flex items-start gap-2 ${disagrees ? 'bg-amber-50 text-amber-900' : 'bg-slate-50 text-slate-700'} rounded-t-lg`}>
        {disagrees ? <TriangleAlert className="w-4 h-4 shrink-0 text-amber-600" /> : <ShieldCheck className="w-4 h-4 shrink-0 text-emerald-600" />}
        <div className="flex-1"><b>{p.agent}</b> {Math.round((p.confidence || 0) * 100)}% - rule agent {disagrees ? <b>disagrees</b> : rc.status === 'agrees' ? 'agrees' : 'not applicable'}
          {rc.detail && <span className="text-slate-500"> - {rc.detail}</span>}
          {p.model && <span className="text-slate-400"> - made by {p.model}</span>}
          <div className="text-slate-500 mt-0.5">{imp.priced && imp.lcr_before != null
            ? <>LCR {(imp.lcr_before * 100).toFixed(2)}% &rarr; {(imp.lcr_after * 100).toFixed(2)}% (net cash outflows {imp.nco_change > 0 ? '+' : ''}{num(imp.nco_change)} mm){imp.review ? ` - above the USD ${imp.threshold} mm review threshold, note your review` : ''}</>
            : (imp.basis || 'No liquidity effect priced')}</div></div>
        <Status s={b.status} /></div>
      <Section icon={BookOpen} title="Sources the agent read" right={`${(p.sources || []).length}`}>
        {(p.sources || []).map((s) => (
          <button key={s.n} onClick={() => setPassage(s)} className="w-full text-left py-1 flex items-start gap-2 hover:bg-slate-50">
            <span className="mt-0.5 px-1.5 rounded bg-blue-100 text-blue-700 text-[10px]">{s.n}</span>
            <span><span className="text-xs text-navy-900">{s.title}</span><span className="block text-[10px] text-slate-400">{s.system}</span></span></button>))}
      </Section>
      <Section icon={Zap} title="How the agents got here" right={`${(p.trace || []).length} steps`}>
        <ol className="space-y-1.5">{(p.trace || []).map((s, i) => (
          <li key={i} className="flex gap-2 text-xs">{s.status === 'warn' ? <TriangleAlert className="w-3.5 h-3.5 text-amber-500 shrink-0" /> : <CircleCheck className="w-3.5 h-3.5 text-emerald-600 shrink-0" />}
            <div><span className="font-semibold text-navy-900">{s.agent}</span> - {s.step}<div className="text-[11px] text-slate-500">{s.detail}</div></div></li>))}</ol>
      </Section>
      {p.source_fix?.text && (
        <Section icon={Wrench} title="Source fix" right={p.source_fix.owner}>
          <div className="text-xs text-slate-700">{p.source_fix.text} <span className="text-slate-400">- due {p.source_fix.due}</span></div>
        </Section>)}
      <Section icon={MessageSquare} title="Ask about this item" right="answers cite their sources"><Ask b={b} onOpen={setPassage} /></Section>
      <div className="border-t border-slate-100 px-3 py-2 space-y-2">
        {b.status === 'PROPOSED' && !ret && (
          <button onClick={() => setRet(true)} className="flex items-center gap-1.5 text-xs text-red-700 hover:underline"><Undo2 className="w-3.5 h-3.5" />Return to the agent with a reason</button>)}
        {ret && (
          <div className="space-y-2">
            <div className="flex items-center text-xs font-semibold text-navy-900">Return to the agent<button onClick={() => setRet(false)} className="ml-auto"><X className="w-3.5 h-3.5 text-slate-400" /></button></div>
            <select value={code} onChange={(e) => setCode(e.target.value)} className="w-full border border-slate-200 rounded px-2 py-1.5 text-xs">
              <option value="">Reason code...</option>{(d.reason_codes?.return || []).map(([c, l]) => <option key={c} value={c}>{c} {l}</option>)}</select>
            <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="What the agent should look at again (required)" className="w-full border border-slate-200 rounded px-2 py-1.5 text-xs" />
            <button disabled={busy || !code || !note.trim()} onClick={sendBack} className="px-3 py-1.5 rounded-lg text-xs font-medium bg-navy-900 text-white disabled:opacity-40">Return to the agent</button>
          </div>)}
        {stp && (
          <div className="space-y-2 text-xs">
            <div className="text-slate-700"><b>Applied straight through by the agents</b> ({String(stp.decided_at || '').replace('T', ' ').slice(0, 16)}) - confidence 95% or more, the rule agent agrees,
              no material LCR effect.{spot ? <> Spot-checked by {spot.decided_by}: <b>{spot.action === 'SPOT_CHECK_CONFIRM' ? 'confirmed' : 'disagreed'}</b>{spot.note ? ` - ${spot.note}` : ''}.</> : ' Spot-check it:'}</div>
            {!spot && (<>
              <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="If you disagree: what is wrong (then fix it with Fix manually)" className="w-full border border-slate-200 rounded px-2 py-1.5 text-xs" />
              <div className="flex gap-2">
                <button disabled={busy} onClick={() => spotCheck('confirm')} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-600 text-white disabled:opacity-40"><CircleCheck className="w-3.5 h-3.5" />Confirm</button>
                <button disabled={busy || !note.trim()} onClick={() => spotCheck('disagree')} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-red-300 text-red-700 disabled:opacity-40"><TriangleAlert className="w-3.5 h-3.5" />Disagree</button>
              </div></>)}
          </div>)}
        {b.status === 'RETURNED' && (
          <button disabled={busy} onClick={again} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-navy-900 text-white disabled:opacity-40">
            <RotateCcw className="w-3.5 h-3.5" />{busy ? 'Agents working...' : 'Run the agent again'}</button>)}
        {msg && <div className="text-xs text-red-600">{msg}</div>}
      </div>
      {passage && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setPassage(null)}>
          <div className="bg-white rounded-xl shadow-xl max-w-2xl w-full m-4" onClick={(e) => e.stopPropagation()}>
            <div className="px-5 py-3 border-b border-slate-100 flex items-center"><span className="font-semibold text-navy-900">{passage.title}</span><button onClick={() => setPassage(null)} className="ml-auto"><X className="w-4 h-4" /></button></div>
            <div className="p-5"><div className="text-[11px] text-slate-500 mb-2">{passage.system}{passage.ref ? ` - ${passage.ref}` : ''}</div>
              <div className="text-xs text-slate-800 bg-slate-50 rounded p-3 whitespace-pre-wrap max-h-96 overflow-y-auto">{passage.passage}</div>
              <div className="text-[10px] text-slate-400 mt-2">Read from the source at the time of the run. The agents cite it; they do not change it.</div></div>
          </div>
        </div>)}
    </div>
  );
}

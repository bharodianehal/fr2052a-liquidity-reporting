import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import StepHeader from '../components/StepHeader';
import Submission from './Submission';
import Markdown from '../components/Markdown';
import { RUNNING } from '../components/StepKit';
import { CheckCircle2, Circle, XCircle, Play, Clock3, ExternalLink, FileText, RefreshCw } from 'lucide-react';

// Step 5: generate and close - it depends on steps 1-4. When they have nothing left, a person generates the 6G files for release
// (fr2052a-generate: app decisions -> corrections -> LCR -> report -> validation + 6G XML -> Lakebase); the approver approves and a
// second person marks the filing submitted. Nothing is reviewed here.
export default function Release({ date }) {
  const [sub, setSub] = useState(null);   // the latest generation and its sign-off status; the Submission panel refreshes it after each action
  const [rv, setRv] = useState(null);     // where steps 1-4 stand (the same counts as Today)
  const [gen, setGen] = useState({});
  const [msg, setMsg] = useState('');
  const [k, setK] = useState(0);
  const loadGen = useCallback(() => { if (date) api.wbGenerateStatus(date).then(setGen).catch(() => {}); }, [date]);
  useEffect(() => { setRv(null); setMsg(''); if (date) { api.agReview(date).then(setRv).catch(() => {}); api.getSubmission(date).then(setSub).catch(() => {}); } loadGen(); }, [date, loadGen, k]);
  const generating = RUNNING.includes(gen.state);
  useEffect(() => {   // follow the generation; refresh the files and the status when it ends
    if (!generating) return undefined;
    const t = setInterval(() => api.wbGenerateStatus(date).then((g) => { setGen(g); if (!RUNNING.includes(g.state)) setK((x) => x + 1); }).catch(() => {}), 15000);
    return () => clearInterval(t);
  }, [generating, date]);

  const left = (rv?.steps || []).slice(0, 4).filter((s) => s.open || s.waiting);
  const ready = rv && left.length === 0;
  const status = sub?.status || '';
  const released = !!sub?.released_by;
  const files = released ? sub?.files || [] : [];
  const canGenerate = ready && !generating && status !== 'SUBMITTED' && (!released || ['REJECTED', 'BLOCKED'].includes(status));
  const stages = [
    ['Steps 1-4 complete', ready, rv ? (left.length ? `${left.length} step(s) with items left` : '') : ''],
    ['Generated for release', released && !generating, generating ? 'generating...' : ''],
    ['Valid against the Fed XSD', files.length > 0 && files.every((f) => f.xsd_valid), files.some((f) => !f.xsd_valid) ? 'schema errors - see the files' : ''],
    ['Approved', released && ['APPROVED', 'SUBMITTED'].includes(status), released && status === 'BLOCKED' ? 'blocked by a failing check' : released && status === 'REJECTED' ? 'rejected' : ''],
    ['Submitted to the Fed', released && status === 'SUBMITTED', ''],
  ];
  const failed = (label) => (label === 'Valid against the Fed XSD' && files.some((f) => !f.xsd_valid)) || (label === 'Approved' && released && ['BLOCKED', 'REJECTED'].includes(status));
  const generate = async () => { setMsg(''); try { const r = await api.wbGenerate(date); setMsg(`Generating the 6G files (job run ${r.run_id}) - about 15 minutes.`); loadGen(); } catch (e) { setMsg(e.message); } };

  return (
    <div className="space-y-4">
      <StepHeader n={5} date={date}>
        Starts when steps 1-4 have nothing left. Generate the 6G files for release (from the fixed report, with the comments accepted in Validate, checked against the Fed XSD), approve them; a second person marks the filing submitted.
      </StepHeader>
      <div className="grid grid-cols-5 gap-3">
        {stages.map(([label, ok, note]) => (
          <div key={label} className={`rounded-xl border px-4 py-3 ${ok ? 'border-emerald-200 bg-emerald-50' : failed(label) ? 'border-red-200 bg-red-50' : 'border-slate-200 bg-white'}`}>
            <div className="flex items-center gap-2 text-sm font-semibold text-navy-900">
              {ok ? <CheckCircle2 className="w-4 h-4 text-emerald-600" /> : failed(label) ? <XCircle className="w-4 h-4 text-red-600" /> : <Circle className="w-4 h-4 text-slate-300" />}{label}</div>
            {note && <div className="text-[11px] text-slate-500 mt-0.5 ml-6">{note}</div>}
          </div>))}
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-3">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-navy-900">Generate the 6G files</h3>
          {gen.state && <span className="text-xs text-slate-500">last generation: <b>{generating ? gen.state.toLowerCase() : (gen.result || gen.state).toLowerCase()}</b>{gen.by ? ` (${gen.by})` : ''}
            {gen.url && <a href={gen.url} target="_blank" rel="noopener noreferrer" className="ml-1 text-blue-700 hover:underline inline-flex items-center gap-0.5">job <ExternalLink className="w-3 h-3" /></a>}</span>}
          <button disabled={!canGenerate} onClick={generate} className="ml-auto flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-navy-900 text-white disabled:opacity-40">
            {generating ? <Clock3 className="w-4 h-4 animate-pulse" /> : <Play className="w-4 h-4" />}{generating ? 'Generating...' : released ? 'Generate again' : 'Generate the 6G files'}</button>
        </div>
        {!rv && <div className="text-xs text-slate-500">Checking steps 1-4...</div>}
        {rv && left.length > 0 && (
          <div className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg p-3 space-y-1">
            <div className="font-semibold">Steps 1-4 first - the files are generated only when nothing is left:</div>
            {left.map((s) => <div key={s.key}><Link to={s.to} className="underline">{s.n}. {s.title}</Link>: {s.open ? s.open_label : s.waiting_label}</div>)}
          </div>)}
        {ready && !released && !generating && <div className="text-xs text-slate-600">Steps 1-4 are complete. Generating runs the day once more with every decision (app decisions, corrections, the LCR, the report, the validation and the 6G XML) and produces the Primary file, the Reduced file at month-end and the Comment file.</div>}
        {msg && <div className="text-xs text-blue-700">{msg}</div>}
      </div>

      {released && !generating && <ReleaseMemo key={`m${k}`} date={date} />}
      {released && <Submission key={k} date={date} embedded onLoad={setSub} canApprove={ready && !generating} />}
    </div>
  );
}

// The release memo for the approver: what is released, what changed since the prior reporting day, how every item was settled, overrides -
// written by the AI from those facts only; kept with the reporting run and included in the examiner pack.
function ReleaseMemo({ date }) {
  const [m, setM] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = (refresh) => { setBusy(true); api.agReleaseMemo(date, refresh).then(setM).catch((e) => setM({ memo: e.message })).finally(() => setBusy(false)); };
  useEffect(() => { setM(null); if (date) load(false); }, [date]);   // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-2">
      <div className="flex items-center gap-2">
        <FileText className="w-4 h-4 text-slate-500" /><h3 className="text-sm font-semibold text-navy-900">Release memo for the approver</h3>
        {m?.made_by && <span className="text-[11px] text-slate-400">written by {m.made_by} from the run's facts{m.created_at ? ` - ${String(m.created_at).replace('T', ' ').slice(0, 16)}` : ''}</span>}
        <button disabled={busy} onClick={() => load(true)} className="ml-auto flex items-center gap-1 text-xs text-blue-700 hover:underline disabled:opacity-40"><RefreshCw className="w-3.5 h-3.5" />Write again</button>
      </div>
      {!m || busy ? <div className="text-xs text-slate-500">The agents are writing the memo...</div>
        : <div className="text-xs text-slate-800 leading-relaxed"><Markdown text={m.memo} /></div>}
    </div>
  );
}

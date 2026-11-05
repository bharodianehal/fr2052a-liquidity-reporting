import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import TodayRun from '../components/TodayRun';
import ReviewChecklist from '../components/ReviewChecklist';
import { Play, CalendarClock, ListChecks, Waves } from 'lucide-react';

// Today: where the filing stands (one row per step: what was done, what is left) and the run (the maturity river).
export default function Today({ date }) {
  const [tab, setTab] = useState('stands');
  const [t, setT] = useState(null);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => { if (date) api.wbToday(date).then(setT).catch((e) => setMsg(e.message)); }, [date]);
  useEffect(load, [load]);

  const run = async () => {
    setBusy(true); setMsg('');
    try { const r = await api.runPipeline(date, 'both'); setMsg(`Run started (job run ${r.run_id}). It takes about 20 minutes; the steps refresh when it finishes.`); }
    catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-navy-900">Today - FR 2052a for {date}</h1>
          <p className="text-sm text-slate-500 mt-1">
            The AI assistant has prepared the filing. Review what it did, step by step, and get the filing ready for submission.
          </p>
          {t && <p className="text-xs text-slate-500 mt-1 flex items-center gap-1"><CalendarClock className="w-3.5 h-3.5" />
            Primary file due {t.due.primary} (T+2 business days); Reduced due {t.due.reduced}. Three reporting entities in one file: ENT001 consolidated, ENT002 bank, ENT003 broker-dealer.</p>}
        </div>
        <button disabled={busy} onClick={run} className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-navy-900 text-white disabled:opacity-40 shrink-0">
          <Play className="w-4 h-4" /> {t?.built ? 'Re-run the day' : 'Run the day'}</button>
      </div>
      {msg && <div className="text-xs text-blue-700">{msg}</div>}
      <div className="flex gap-2 border-b border-slate-200">
        {[['stands', 'Where it stands', ListChecks], ['run', 'The run', Waves]].map(([k, label, Icon]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 -mb-px ${tab === k ? 'border-blue-600 text-navy-900' : 'border-transparent text-slate-500 hover:text-slate-700'}`}>
            <Icon className="w-4 h-4" />{label}</button>
        ))}
      </div>
      {tab === 'run' && <TodayRun date={date} />}
      {tab === 'stands' && <ReviewChecklist date={date} />}
    </div>
  );
}

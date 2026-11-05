import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { CircleCheck, Clock3, ChevronRight, Bot } from 'lucide-react';

// Where it stands: one row per step - what was done (plain facts with the numbers), and on the right what is left for you,
// counted from the step page's own queue, so the numbers match where you click.
export default function ReviewChecklist({ date }) {
  const [r, setR] = useState(null);
  useEffect(() => { setR(null); if (date) api.agReview(date).then(setR).catch(() => setR(false)); }, [date]);
  if (r === false) return <div className="text-sm text-slate-500">Not available for this day.</div>;
  if (!r) return <div className="text-sm text-slate-500">Checking where the filing stands...</div>;
  const ag = r.agents || {};
  return (
    <div className="space-y-3">
      {ag.headline && (
        <div className="bg-blue-50 border border-blue-100 rounded-xl px-5 py-3 text-sm text-navy-900 flex items-start gap-3">
          <Bot className="w-5 h-5 text-blue-700 shrink-0 mt-0.5" />
          <div className="flex-1"><div>{ag.headline}</div>
            {(ag.spot_check || []).length > 0 && (
              <div className="mt-1.5 text-xs text-slate-600">Applied straight through - spot-check:{' '}
                {ag.spot_check.map((x, i) => <span key={x.break_id}>{i > 0 && ', '}<Link to={`/breaks/${x.break_id}`} className="text-blue-700 hover:underline">{x.title.slice(0, 60)}</Link></span>)}</div>)}</div>
        </div>)}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm divide-y divide-slate-100">
        {r.steps.map((s) => (
          <Link key={s.key} to={s.to} className="flex items-start gap-4 px-5 py-4 hover:bg-slate-50">
            <span className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold shrink-0 ${s.state === 'done' ? 'bg-emerald-100 text-emerald-700' : s.state === 'waiting' ? 'bg-slate-100 text-slate-600' : 'bg-blue-600 text-white'}`}>
              {s.state === 'done' ? <CircleCheck className="w-4 h-4" /> : s.n}</span>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-navy-900">{s.n}. {s.title}</div>
              <ul className="mt-1 space-y-0.5 list-disc pl-4 text-xs text-slate-600">
                {(s.done || [s.agent]).map((line) => <li key={line}>{line}</li>)}
              </ul>
            </div>
            <div className="text-right shrink-0 w-72 pt-0.5">
              {s.open > 0 ? <span className="text-sm font-semibold text-blue-700">{s.open_label} &rarr;</span>
                : s.close_label ? (s.tone === 'wait' ? <span className="text-sm text-slate-500 flex items-center justify-end gap-1"><Clock3 className="w-3.5 h-3.5" />{s.close_label}</span>
                  : s.tone === 'done' ? <span className="text-sm text-emerald-700">{s.close_label}</span>
                    : <span className="text-sm font-semibold text-blue-700">{s.close_label} &rarr;</span>)
                  : <span className="text-sm text-emerald-700">Nothing to review</span>}
              {s.waiting > 0 && <div className="text-[11px] text-slate-500 flex items-center justify-end gap-1"><Clock3 className="w-3 h-3" />{s.waiting_label}</div>}
            </div>
            <ChevronRight className="w-4 h-4 text-slate-300 mt-0.5" />
          </Link>))}
      </div>
      {r.next && <p className="text-xs text-slate-500">{r.next}</p>}
    </div>
  );
}

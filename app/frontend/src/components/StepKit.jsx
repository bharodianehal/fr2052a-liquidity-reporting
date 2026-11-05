import React from 'react';
import { RotateCcw, Sparkles, ChevronLeft, ChevronRight, Search, CircleCheck } from 'lucide-react';

// The one layout every step page uses:
//   StepHeader
//   StepTabs      [Needs review (N)] [Browse ...]                      right: bulk approve | last re-run | Re-run <step>
//   Needs review  QueueFilters (To review / Decided / All [+ rule, search])
//                 Queue (left)  |  Detail (right): what is wrong -> AiFix -> Actions -> agent evidence
//   Browse        the step's data
export const RUNNING = ['PENDING', 'QUEUED', 'RUNNING', 'BLOCKED'];

// One status language for every queue item.
const STATE = {
  review: ['To review', 'bg-red-50 text-red-700 border-red-200'],
  rerun: ['Decided - re-run', 'bg-blue-50 text-blue-700 border-blue-200'],
  done: ['Decided', 'bg-emerald-50 text-emerald-700 border-emerald-200'],
  excluded: ['Excluded', 'bg-slate-100 text-slate-600 border-slate-200'],
  explained: ['Explained', 'bg-slate-100 text-slate-600 border-slate-200'],
  warning: ['Warning only', 'bg-amber-50 text-amber-700 border-amber-200'],
};
export const Pill = ({ s }) => { const [l, c] = STATE[s] || STATE.review; return <span className={`text-[10px] px-1.5 py-0.5 rounded border whitespace-nowrap ${c}`}>{l}</span>; };
export const isOpen = (s) => s === 'review';
export const isDecided = (s) => !['review', 'warning'].includes(s);

export function StepTabs({ tabs, tab, setTab, children }) {
  return (
    <div className="flex items-center gap-2 border-b border-slate-200">
      {tabs.map(([k, label]) => (
        <button key={k} onClick={() => setTab(k)}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${tab === k ? 'border-blue-600 text-navy-900' : 'border-transparent text-slate-500 hover:text-slate-700'}`}>{label}</button>))}
      <div className="ml-auto flex items-center gap-3 pb-1">{children}</div>
    </div>
  );
}

export function Rerun({ run, label, onClick }) {
  const running = RUNNING.includes(run?.state);
  return (<>
    {run?.state && <span className="text-xs text-slate-500">last re-run: <b>{running ? run.state.toLowerCase() : (run.result || run.state).toLowerCase()}</b></span>}
    <button disabled={running} onClick={onClick} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-navy-900 text-white disabled:opacity-40">
      <RotateCcw className={`w-3.5 h-3.5 ${running ? 'animate-spin' : ''}`} /> {running ? 'Re-running...' : label}</button>
  </>);
}

export function QueueFilters({ filter, setFilter, counts, rules, search = true }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {[['open', 'To review'], ['done', 'Decided'], ['all', 'All']].map(([k, label]) => (
        <button key={k} onClick={() => setFilter({ ...filter, state: k })}
          className={`px-3 py-1.5 rounded-lg text-xs border ${filter.state === k ? 'bg-navy-900 text-white border-navy-900' : 'bg-white border-slate-200 text-slate-700'}`}>
          {label} <b>{counts[k]}</b></button>))}
      {rules && rules.length > 1 && (
        <select value={filter.rule || ''} onChange={(e) => setFilter({ ...filter, rule: e.target.value })} className="text-xs border border-slate-200 rounded px-2 py-1.5 bg-white">
          <option value="">All rules ({rules.length})</option>
          {rules.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>)}
      {search && (
        <div className="flex items-center gap-1 border border-slate-200 rounded px-2 bg-white"><Search className="w-3.5 h-3.5 text-slate-400" />
          <input value={filter.q || ''} onChange={(e) => setFilter({ ...filter, q: e.target.value })} placeholder="search..." className="text-xs py-1.5 outline-none w-40" /></div>)}
    </div>
  );
}

// Applies the To review / Decided / All chip, the rule filter and the search to a queue of items carrying a common `s` state.
export function filterQueue(items, filter, ruleOf) {
  return items.filter((r) => (filter.state === 'all' || (filter.state === 'open' ? isOpen(r.s) : isDecided(r.s)))
    && (!filter.rule || (ruleOf && ruleOf(r) === filter.rule)) && (!filter.q || JSON.stringify(r).toLowerCase().includes(filter.q.toLowerCase())));
}
export const queueCounts = (items) => ({ open: items.filter((r) => isOpen(r.s)).length, done: items.filter((r) => isDecided(r.s)).length, all: items.length });

// Left: the list, one row per item (tag, title, state, one detail line); right: the item.
export function Queue({ items, keyOf, sel, setSel, row, noun, children }) {
  const idx = items.findIndex((r) => keyOf(r) === sel);
  return (
    <div className="grid grid-cols-5 gap-4" style={{ minHeight: '30rem' }}>
      <div className="col-span-2 bg-white rounded-xl border border-slate-200 shadow-sm flex flex-col">
        <div className="px-4 py-2 border-b border-slate-100 text-xs text-slate-500 flex items-center">{items.length} {noun}{items.length === 1 ? '' : 's'}
          <span className="ml-auto flex gap-1">
            <button disabled={idx <= 0} onClick={() => setSel(keyOf(items[idx - 1]))} className="p-1 rounded border border-slate-200 disabled:opacity-30"><ChevronLeft className="w-3.5 h-3.5" /></button>
            <button disabled={idx < 0 || idx >= items.length - 1} onClick={() => setSel(keyOf(items[idx + 1]))} className="p-1 rounded border border-slate-200 disabled:opacity-30"><ChevronRight className="w-3.5 h-3.5" /></button>
          </span></div>
        <div className="overflow-y-auto max-h-[38rem]">
          {items.length === 0 && <div className="p-4 text-xs text-emerald-700">Nothing in this view.</div>}
          {items.map((r) => {
            const [tag, title, line] = row(r);
            return (
              <button key={keyOf(r)} onClick={() => setSel(keyOf(r))} className={`w-full text-left px-4 py-2 border-t border-slate-100 first:border-t-0 ${keyOf(r) === sel ? 'bg-blue-50' : 'hover:bg-slate-50'}`}>
                <div className="flex items-center gap-2">{tag && <span className="text-[10px] text-slate-500 shrink-0">{tag}</span>}<span className="text-xs font-medium text-navy-900 truncate">{title}</span>
                  <span className="ml-auto"><Pill s={r.s} /></span></div>
                {line && <div className="text-[10px] text-slate-400 truncate">{line}</div>}
              </button>);
          })}
        </div>
      </div>
      <div className="col-span-3">{children}</div>
    </div>
  );
}

export function Detail({ tag, title, s, sub, children }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
      <div className="px-5 py-3 border-b border-slate-100">
        <div className="flex items-center gap-2">{tag && <span className="text-[11px] px-2 py-0.5 rounded bg-slate-100 text-slate-600">{tag}</span>}
          <span className="text-sm font-semibold text-navy-900">{title}</span>{s && <span className="ml-auto"><Pill s={s} /></span>}</div>
        {sub && <div className="text-[11px] text-slate-400 mt-0.5">{sub}</div>}
      </div>
      <div className="p-5 space-y-4">{children}</div>
    </div>
  );
}

export function AiFix({ confidence, loading, title, rationale }) {
  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-blue-900"><Sparkles className="w-4 h-4" />AI-suggested fix
        {confidence != null && <span className="font-normal text-blue-700">confidence {Math.round(parseFloat(confidence) * 100)}%</span>}</div>
      {loading ? <div className="text-xs text-blue-800 mt-1 animate-pulse">Looking at the item...</div> : <>
        <div className="text-sm text-navy-900 mt-1 font-medium">{title}</div>
        {rationale && <div className="text-xs text-slate-600 mt-0.5 line-clamp-6">{String(rationale).replace(/\*\*/g, '')}</div>}</>}
    </div>
  );
}

// The buttons, always in this order: the AI fix (primary), then the person's alternatives.
export function Actions({ children }) { return <div className="flex flex-wrap gap-2">{children}</div>; }
export function Btn({ primary, active, icon: I, children, ...p }) {
  const cls = primary ? 'bg-emerald-600 text-white border-emerald-600' : active ? 'bg-navy-900 text-white border-navy-900' : 'border-slate-300 text-slate-700 bg-white';
  return <button {...p} className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium border disabled:opacity-40 ${cls}`}>{I && <I className="w-4 h-4" />}{children}</button>;
}

export const Decided = ({ children }) => <div className="text-xs bg-slate-50 rounded p-2">{children}</div>;

export function AllClear({ children }) {
  return <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4 text-sm text-emerald-800 flex items-center gap-2"><CircleCheck className="w-4 h-4" />{children}</div>;
}

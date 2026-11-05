import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { Download, X, Lock, Bot } from 'lucide-react';

const initials = (s) => (s || '?').split(/[.@\s]/).filter(Boolean).slice(0, 2).map((x) => x[0].toUpperCase()).join('');
const ts = (v) => String(v || '').replace('T', ' ').slice(0, 16);

// The audit trail: who did what, when, why and with which evidence - people and AI agents - and the examiner pack.
export default function Audit({ date }) {
  const [who, setWho] = useState('all');
  const [d, setD] = useState(null);
  const [fixes, setFixes] = useState([]);
  const [exp, setExp] = useState(false);
  const [aud, setAud] = useState('Federal Reserve examiners');
  useEffect(() => { setD(null); if (date) api.agAudit(date, who).then(setD).catch(() => setD({ events: [], total: 0 })); }, [date, who]);
  useEffect(() => { if (date) api.agSourceFixes(date).then(setFixes).catch(() => setFixes([])); }, [date]);
  const [acc, setAcc] = useState(null);
  const [learn, setLearn] = useState([]);
  useEffect(() => { api.agAccuracy().then(setAcc).catch(() => setAcc({ agents: [], evaluation: [] })); api.agLearning().then(setLearn).catch(() => setLearn([])); }, []);
  const pct = (v) => (v == null ? '-' : `${Math.round(v * 100)}%`);
  return (
    <div className="space-y-4">
      <div className="flex items-start gap-4">
        <div><h1 className="text-xl font-bold text-navy-900">Audit trail</h1>
          <p className="text-sm text-slate-500 mt-1">Who did what, when, why and with which evidence - people and AI agents - for {date}. The agents' events and the checkers'
            decisions are append-only: the app can add to them but not change or delete them.</p></div>
        <button onClick={() => setExp(true)} className="ml-auto flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-blue-600 text-white shrink-0"><Download className="w-4 h-4" />Export for examiners</button>
      </div>
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <div className="px-4 py-2.5 border-b border-slate-100 flex items-center gap-1">
          {[['all', 'Everything'], ['people', 'People'], ['agents', 'Agents'], ['decisions', 'Decisions']].map(([k, l]) => (
            <button key={k} onClick={() => setWho(k)} className={`px-3 py-1 rounded text-xs ${who === k ? 'bg-navy-900 text-white' : 'text-slate-600 hover:bg-slate-100'}`}>{l}</button>))}
          <span className="ml-auto text-[11px] text-slate-400">{d ? `${Math.min(d.events.length, 500)} of ${d.total} events` : 'Loading...'}</span>
        </div>
        <div className="max-h-[36rem] overflow-y-auto">
          {(d?.events || []).map((e, i) => (
            <div key={i} className="px-4 py-2.5 border-t border-slate-100 first:border-t-0 flex gap-3 text-xs">
              <span className="w-32 shrink-0 text-slate-500">{ts(e.ts)}</span>
              <span className={`w-7 h-7 shrink-0 rounded-full flex items-center justify-center text-[10px] font-semibold ${e.actor_type === 'AI' ? 'bg-blue-50 text-blue-700' : 'bg-slate-100 text-slate-700'}`}>
                {e.actor_type === 'AI' ? <Bot className="w-3.5 h-3.5" /> : initials(e.actor)}</span>
              <div className="flex-1 min-w-0"><span className="font-semibold text-navy-900">{e.actor}</span> {e.action}
                <span className="text-slate-400"> - {String(e.subject || '').startsWith('BRK-') ? <Link to={`/breaks/${e.subject}`} className="text-blue-700 hover:underline">{e.subject}</Link> : e.subject}</span>
                <div className="text-[11px] text-slate-500">{e.why && <>Why: {e.why}</>}{e.evidence && <span className="ml-3">Evidence: {e.evidence}</span>}{e.version && <span className="ml-3">{e.version}</span>}</div></div>
            </div>))}
          {d && d.events.length === 0 && <div className="p-4 text-xs text-slate-500">No events for this day yet.</div>}
        </div>
      </div>
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <div className="px-4 py-2.5 border-b border-slate-100 text-sm font-semibold text-navy-900">Source fixes <span className="font-normal text-xs text-slate-500">- from the approved breaks; an override retires when the source sends the corrected value</span></div>
        <table className="w-full text-xs"><thead className="text-slate-400 bg-slate-50"><tr><th className="text-left px-4 py-1.5">Break</th><th className="text-left px-3">Data owner</th><th className="text-left px-3">Fix at source</th>
          <th className="text-left px-3">Due</th><th className="text-right px-3">Age (bd)</th><th className="text-left px-3">Status</th></tr></thead>
          <tbody>{fixes.length === 0 && <tr><td colSpan={6} className="px-4 py-3 text-slate-500">No source fixes - nothing approved yet for this day.</td></tr>}
            {fixes.map((f) => (
              <tr key={f.break_id} className="border-t border-slate-100 align-top"><td className="px-4 py-2"><Link to={`/breaks/${f.break_id}`} className="font-mono text-blue-700 hover:underline">{f.break_id}</Link>
                <div className="text-[10px] text-slate-400">{f.break_type}</div></td><td className="px-3 py-2">{f.owner}</td><td className="px-3 py-2 text-slate-700">{f.text}</td>
                <td className="px-3 py-2 whitespace-nowrap">{f.due}</td><td className="px-3 py-2 text-right">{f.age_business_days}</td>
                <td className={`px-3 py-2 whitespace-nowrap ${f.status === 'OVERDUE' ? 'text-red-700 font-semibold' : f.status.startsWith('RETIRED') ? 'text-emerald-700' : 'text-slate-700'}`}>{f.status}</td></tr>))}</tbody></table>
      </div>
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <div className="px-4 py-2.5 border-b border-slate-100 text-sm font-semibold text-navy-900">How the agents do <span className="font-normal text-xs text-slate-500">- all reporting days, from the checkers' decisions{acc?.model ? `; registered model ${acc.model}` : ''}</span></div>
        <table className="w-full text-xs"><thead className="text-slate-400 bg-slate-50"><tr><th className="text-left px-4 py-1.5">Agent</th><th className="text-right px-3">Proposals</th>
          <th className="text-right px-3">Accepted</th><th className="text-right px-3">Edited</th><th className="text-right px-3">Returned</th><th className="text-right px-3">Straight through</th><th className="text-right px-3">Spot checks agreed</th></tr></thead>
          <tbody>{(acc?.agents || []).map((a) => (
            <tr key={a.agent} className="border-t border-slate-100"><td className="px-4 py-1.5 font-semibold text-navy-900">{a.agent}</td><td className="px-3 text-right">{a.proposals}</td>
              <td className="px-3 text-right">{pct(a.acceptance)}</td><td className="px-3 text-right">{pct(a.edit_rate)}</td><td className="px-3 text-right">{a.returned}</td>
              <td className="px-3 text-right">{a.straight_through}</td><td className="px-3 text-right">{a.spot_confirmed + a.spot_disagreed ? `${pct(a.spot_agreement)} of ${a.spot_confirmed + a.spot_disagreed}` : '-'}</td></tr>))}
            {acc && !acc.agents.length && <tr><td colSpan={7} className="px-4 py-3 text-slate-500">No proposals yet.</td></tr>}</tbody></table>
        {(acc?.evaluation || []).length > 0 && (
          <div className="px-4 py-2.5 border-t border-slate-100 text-[11px] text-slate-600">GenAI evaluation of the champion ({acc.evaluation[0].eval_run}, {acc.evaluation[0].n} proposals):{' '}
            {acc.evaluation.map((e) => `${e.metric.replace(/\.mean$|\/mean$/, '').replace(/_/g, ' ')} ${e.value <= 1 ? pct(e.value) : e.value}`).join(' - ')}</div>)}
      </div>
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <div className="px-4 py-2.5 border-b border-slate-100 text-sm font-semibold text-navy-900">Recurring fixes <span className="font-normal text-xs text-slate-500">- the same fix on several reporting days: the agents propose the permanent fix at the source</span></div>
        <table className="w-full text-xs"><thead className="text-slate-400 bg-slate-50"><tr><th className="text-left px-4 py-1.5">What keeps happening</th><th className="text-left px-3">Days</th>
          <th className="text-left px-3">Permanent fix proposed</th><th className="text-left px-3">Owner</th></tr></thead>
          <tbody>{learn.length === 0 && <tr><td colSpan={4} className="px-4 py-3 text-slate-500">No fix has recurred yet.</td></tr>}
            {learn.map((x, i) => (
              <tr key={i} className="border-t border-slate-100 align-top"><td className="px-4 py-2"><div className="text-[10px] text-slate-400">{x.kind}</div>{x.pattern}</td>
                <td className="px-3 py-2 whitespace-nowrap">{x.days.length} ({x.days.map((d) => d.slice(5)).join(', ')})</td><td className="px-3 py-2 text-slate-700">{x.proposal}</td><td className="px-3 py-2">{x.owner}</td></tr>))}</tbody></table>
      </div>
      {exp && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setExp(false)}>
          <div className="bg-white rounded-xl shadow-xl max-w-xl w-full m-4" onClick={(e) => e.stopPropagation()}>
            <div className="px-5 py-3 border-b border-slate-100 flex items-center"><span className="font-semibold text-navy-900">Export the audit pack</span><button onClick={() => setExp(false)} className="ml-auto"><X className="w-4 h-4" /></button></div>
            <div className="p-5 space-y-4 text-xs">
              <div><div className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">For</div>
                <div className="flex gap-1">{['Federal Reserve examiners', 'Internal audit', 'ALCO'].map((a) => (
                  <button key={a} onClick={() => setAud(a)} className={`px-3 py-1.5 rounded-lg border ${aud === a ? 'bg-navy-900 text-white border-navy-900' : 'border-slate-200'}`}>{a}</button>))}</div></div>
              <div><div className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Scope</div>{date} run - all reporting entities</div>
              <div><div className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Contents</div>
                <ul className="list-disc ml-4 space-y-0.5 text-slate-700"><li>Decisions with reason codes and checker signatures</li><li>Breaks, and every proposal with its agent, model, confidence, rule check, liquidity effect and sources</li>
                  <li>Source fixes with aging</li><li>The audit trail of agents and people</li><li>Agent and model versions</li><li>Lineage counts from each FR 2052a table to its positions</li><li>The release memo given to the approver</li></ul></div>
              <div className="rounded-lg bg-slate-50 p-3 flex gap-2 text-slate-700"><Lock className="w-4 h-4 shrink-0" />Customer identifiers and names are masked. Marked confidential: FR 2052a data receives
                confidential treatment (12 CFR 261). No BSA/AML case information is held in this solution. Each file's SHA-256 is in the manifest.</div>
              <a href={api.agAuditExportUrl(date, aud)} onClick={() => setTimeout(() => setExp(false), 500)} className="block text-center px-4 py-2 rounded-lg bg-blue-600 text-white font-medium">Build and download the pack</a>
            </div>
          </div>
        </div>)}
    </div>
  );
}

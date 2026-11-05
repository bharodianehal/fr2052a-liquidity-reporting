import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { NavLink } from 'react-router-dom';
import { ListChecks, Layers, Sparkles, BookOpen, History, GitBranch, Table2, Droplets, ScrollText } from 'lucide-react';
import { STEPS } from './StepHeader';

const linkCls = ({ isActive }) => `sidebar-link ${isActive ? 'active' : 'text-slate-300'}`;

const RUNNING = ['PENDING', 'QUEUED', 'RUNNING', 'BLOCKED'];

// Demo environment only: a faint link that puts the demo dates back to "nothing worked yet" (job fr2052a-demo-reset).
function DemoReset() {
  const [st, setSt] = useState({});
  const [msg, setMsg] = useState('');
  useEffect(() => { api.demoResetStatus().then(setSt).catch(() => {}); }, []);
  useEffect(() => {
    if (!RUNNING.includes(st.state)) return undefined;
    const t = setInterval(() => api.demoResetStatus().then(setSt).catch(() => {}), 30000);
    return () => clearInterval(t);
  }, [st.state]);
  const running = RUNNING.includes(st.state);
  const go = async () => {
    if (running || !window.confirm('Reset the demo dates (Feb 23-27)? Everything decided on them is removed and the days re-run (about 25 minutes).')) return;
    setMsg('');
    try { await api.demoReset(); setSt({ state: 'PENDING' }); } catch (e) { setMsg(e.message); }
  };
  return (
    <div className="text-[9px] text-center mt-1">
      <button onClick={go} className="text-navy-800 hover:text-slate-500">{running ? 'resetting...' : 'reset'}</button>
      {msg && <div className="text-slate-500">{msg}</div>}
    </div>
  );
}

// Navigation follows the analyst's day: Today, the five steps in order, then the support pages.
export default function Sidebar() {
  return (
    <aside className="w-56 bg-navy-950 text-slate-300 flex flex-col shrink-0">
      <div className="h-14 flex items-center px-5 border-b border-navy-800">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
            <Layers className="w-4 h-4 text-white" />
          </div>
          <div>
            <div className="text-[11px] font-bold text-white tracking-tight leading-tight">FR 2052a</div>
            <div className="text-[10px] text-slate-400 -mt-0.5">Liquidity reporting</div>
          </div>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto py-4 px-3 space-y-0.5">
        <NavLink to="/" end className={linkCls}><ListChecks className="w-4 h-4" /><span>Today</span></NavLink>

        <div className="px-3 pt-4 pb-1 text-[10px] uppercase tracking-wider text-slate-500">The day, step by step</div>
        {STEPS.map((s) => (
          <NavLink key={s.to} to={s.to} className={linkCls}>
            <span className="w-5 h-5 rounded-full border border-slate-500 text-[10px] flex items-center justify-center">{s.n}</span>
            <span>{s.title}</span>
          </NavLink>
        ))}

        <div className="px-3 pt-4 pb-1 text-[10px] uppercase tracking-wider text-slate-500">Any time</div>
        <NavLink to="/genie" className={linkCls}><Sparkles className="w-4 h-4" /><span>Genie</span></NavLink>
        <NavLink to="/dashboard" className={linkCls}><Table2 className="w-4 h-4" /><span>Dashboard</span></NavLink>
        <NavLink to="/lineage" className={linkCls}><GitBranch className="w-4 h-4" /><span>Lineage</span></NavLink>
        <NavLink to="/reference" className={linkCls}><BookOpen className="w-4 h-4" /><span>Reference</span></NavLink>
        <NavLink to="/audit" className={linkCls}><ScrollText className="w-4 h-4" /><span>Audit</span></NavLink>
        <NavLink to="/history" className={linkCls}><History className="w-4 h-4" /><span>History</span></NavLink>

        <div className="px-3 pt-4 pb-1 text-[10px] uppercase tracking-wider text-slate-500">Liquidity risk</div>
        <NavLink to="/lcr" className={linkCls}><Droplets className="w-4 h-4" /><span>LCR</span></NavLink>
      </nav>

      <div className="p-4 border-t border-navy-800">
        <div className="text-[10px] text-slate-500 text-center">Powered by Databricks</div>
        <div className="text-[10px] text-slate-600 text-center mt-0.5">Federal Reserve FR 2052a | 6G | synthetic data</div>
        <DemoReset />
      </div>
    </aside>
  );
}

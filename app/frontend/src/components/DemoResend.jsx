import React, { useState, useEffect, useRef } from 'react';
import { Send, X } from 'lucide-react';
import { api } from '../api';

// Demo only (not part of the product): the source system re-sends a feed that arrived short. Pick the date(s); each day re-runs
// with the re-sent file (fr2052a-daily, resend_feed) and the feed clears on Collect when the run finishes (about 40 minutes).
export default function DemoResend() {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState(null);
  const [sel, setSel] = useState({});
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const ref = useRef(null);
  const load = () => api.demoResendOptions().then(setRows).catch((e) => setMsg(e.message));
  useEffect(() => { if (open) { setMsg(''); setSel({}); load(); } }, [open]);
  useEffect(() => {
    const away = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, []);
  const chosen = (rows || []).filter((r) => sel[r.date]);
  const go = async () => {
    setBusy(true); setMsg('');
    const out = [];
    for (const r of chosen) {
      for (const f of r.feeds) {
        try { await api.wbResend(r.date, f.feed); out.push(`${r.date} ${f.feed}: re-running`); } catch (e) { out.push(`${r.date} ${f.feed}: ${e.message}`); }
      }
    }
    setMsg(out.join(' | ')); setSel({}); setBusy(false); load();
  };
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(!open)} title="Demo: the source re-sends a short feed"
        className="w-8 h-8 rounded-full flex items-center justify-center bg-slate-500 text-white hover:bg-slate-600 transition-colors shadow-sm">
        <Send className="w-4 h-4" />
      </button>
      {open && (
        <div className="absolute right-0 mt-2 w-96 bg-white border border-slate-200 rounded-xl shadow-lg z-50 p-4 space-y-3">
          <div className="flex items-start justify-between">
            <div>
              <div className="text-sm font-semibold text-navy-900">Demo: the source re-sends a short feed</div>
              <div className="text-xs text-slate-500 mt-0.5">Pick the date(s). Each day re-runs with the re-sent file (about 40 minutes); the feed then clears on Collect.</div>
            </div>
            <button onClick={() => setOpen(false)} className="text-slate-400 hover:text-slate-600"><X className="w-4 h-4" /></button>
          </div>
          {!rows ? <div className="text-xs text-slate-500">Loading...</div> : (
            <div className="divide-y divide-slate-100 border border-slate-100 rounded-lg">
              {rows.map((r) => {
                const can = r.feeds.length > 0 && !r.running;
                return (
                  <label key={r.date} className={`flex items-center gap-3 px-3 py-2 text-xs ${can ? 'cursor-pointer' : 'text-slate-400'}`}>
                    <input type="checkbox" disabled={!can} checked={!!sel[r.date]} onChange={(e) => setSel({ ...sel, [r.date]: e.target.checked })} />
                    <span className="font-semibold w-20">{r.date}</span>
                    <span className="flex-1">{r.feeds.length === 0 ? 'all feeds complete'
                      : r.feeds.map((f) => `${f.feed} ${f.records} of ~${Math.round(f.expected_records)}`).join(', ')}</span>
                    {r.running && <span className="text-blue-700">running</span>}
                  </label>);
              })}
            </div>)}
          <div className="flex items-center justify-end">
            <button disabled={busy || chosen.length === 0} onClick={go}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-navy-900 text-white disabled:opacity-40">
              <Send className="w-3.5 h-3.5" /> {busy ? 'Starting...' : `Re-send${chosen.length ? ` (${chosen.length})` : ''}`}</button>
          </div>
          {msg && <div className="text-xs text-slate-600">{msg}</div>}
        </div>)}
    </div>
  );
}

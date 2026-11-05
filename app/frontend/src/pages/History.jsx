import React, { useState } from 'react';
import Workbench from './Workbench';
import ReportAudit from './ReportAudit';

// History: every as-of date and its filing state (click a day to open it in Today), and the sign-off / pipeline audit trail.
export default function History({ date, onDateChange }) {
  const [tab, setTab] = useState('days');
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold text-navy-900">History</h1>
      <div className="flex gap-2">
        {[['days', 'Reporting days'], ['audit', 'Sign-off & pipeline audit trail']].map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium border ${tab === k ? 'bg-navy-900 text-white border-navy-900' : 'bg-white border-slate-200 text-slate-700'}`}>{label}</button>
        ))}
      </div>
      {tab === 'days' ? <Workbench date={date} onDateChange={onDateChange} embedded /> : <ReportAudit embedded />}
    </div>
  );
}

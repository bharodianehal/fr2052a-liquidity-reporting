import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';


const STATUS_STYLE = {
  READY_FOR_REVIEW: 'text-amber-700', BLOCKED: 'text-red-700', APPROVED: 'text-blue-700', REJECTED: 'text-red-700',
  SUBMITTED: 'text-emerald-700', OVERRIDE_REQUESTED: 'text-purple-700', REPORTING_REQUESTED: 'text-slate-600',
};

// Every reporting day and the state of its filing; clicking a day opens it in Today.
export default function Workbench({ date, onDateChange }) {
  const navigate = useNavigate();
  const [days, setDays] = useState([]);
  const [error, setError] = useState('');

  useEffect(() => { api.wbCalendar().then(setDays).catch((e) => setError(e.message)); }, []);

  return (
    <div className="space-y-5">
      <p className="text-sm text-slate-500">One row per business day: the latest reporting run and its sign-off state, failed checks, Fed
        post-submission checks, feed issues, AI proposals waiting and unusual movements. Click a day to open it in Today.</p>
      {error && <div className="text-xs text-red-600">{error}</div>}

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead className="text-xs text-slate-500 bg-slate-50">
            <tr><th className="text-left px-4 py-2">As-of date</th><th className="text-left">Due (Primary)</th><th className="text-left">Run</th>
              <th className="text-left">Status</th><th className="text-right">Fails</th><th className="text-right">Warnings</th>
              <th className="text-right">Fed checks</th><th className="text-right">Feeds</th><th className="text-right">AI to review</th>
              <th className="text-right pr-4">Anomalies</th></tr>
          </thead>
          <tbody>
            {days.map((d) => {
              const ds = String(d.as_of_date);
              return (
                <tr key={ds} onClick={() => { onDateChange(ds); navigate('/'); }}
                  className={`border-t border-slate-100 cursor-pointer hover:bg-slate-50 ${ds === date ? 'bg-blue-50/60' : ''}`}>
                  <td className="px-4 py-1.5 font-mono text-xs">{ds}</td>
                  <td className="text-xs">{d.due}</td>
                  <td className="text-xs">{d.run_number}</td>
                  <td className={`text-xs font-semibold ${STATUS_STYLE[d.status] || ''}`}>{(d.status || '').replace(/_/g, ' ')}</td>
                  <td className={`text-right text-xs ${d.fails ? 'text-red-700 font-semibold' : ''}`}>{d.fails ?? 0}</td>
                  <td className="text-right text-xs">{d.warnings ?? 0}</td>
                  <td className={`text-right text-xs ${d.psv ? 'text-amber-700 font-semibold' : ''}`}>{d.psv ?? 0}</td>
                  <td className={`text-right text-xs ${d.feed_issues ? 'text-amber-700 font-semibold' : ''}`}>{d.feed_issues}</td>
                  <td className="text-right text-xs">{d.open_ai || ''}</td>
                  <td className="text-right text-xs pr-4">{d.anomalies || ''}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

    </div>
  );
}

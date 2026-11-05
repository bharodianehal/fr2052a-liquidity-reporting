import React, { useState } from 'react';
import Metadata from './Metadata';
import Configuration from './Configuration';
import UserGuide from './UserGuide';

// Reference: what a PID means and which rules assign it; the reference data and rules; the user guide.
export default function Reference() {
  const [tab, setTab] = useState('pid');
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold text-navy-900">Reference</h1>
      <div className="flex gap-2">
        {[['pid', 'PID dictionary'], ['config', 'Reference data & rules'], ['guide', 'User guide']].map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium border ${tab === k ? 'bg-navy-900 text-white border-navy-900' : 'bg-white border-slate-200 text-slate-700'}`}>{label}</button>
        ))}
      </div>
      {tab === 'pid' && <Metadata />}
      {tab === 'config' && <Configuration embedded />}
      {tab === 'guide' && <UserGuide embedded />}
    </div>
  );
}

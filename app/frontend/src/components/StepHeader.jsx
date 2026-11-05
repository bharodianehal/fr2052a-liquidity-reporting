import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, ArrowRight } from 'lucide-react';

// The five steps of the FR 2052a day, in order. Every step page shows where it sits and links to the next step.
export const STEPS = [
  { n: 1, key: 'collect', to: '/collect', title: 'Collect', question: 'Did every source file arrive and load into Bronze?' },
  { n: 2, key: 'dq', to: '/dq', title: 'Data quality', question: 'Which records pass the data quality rules - and can the failed ones be fixed?' },
  { n: 3, key: 'enrich', to: '/enrich', title: 'PID enrichment', question: 'Has every position its counterparty, currency, product (PID) and other FR 2052a attributes?' },
  { n: 4, key: 'validate', to: '/validate', title: 'Validate', question: 'Does every rule pass on the report tables?' },
  { n: 5, key: 'release', to: '/release', title: 'Generate 6G & release', question: 'Is the 6G file valid against the Fed XSD and signed off for the Federal Reserve?' },
];

export default function StepHeader({ n, date, children }) {
  const step = STEPS[n - 1];
  const prev = STEPS[n - 2];
  const next = STEPS[n];
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5">
        {STEPS.map((s) => (
          <Link key={s.n} to={s.to}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium border ${s.n === n ? 'bg-navy-900 text-white border-navy-900' : s.n < n ? 'bg-blue-50 text-blue-700 border-blue-100' : 'bg-white text-slate-500 border-slate-200'}`}>
            <span className="w-4 h-4 rounded-full bg-white/20 flex items-center justify-center text-[10px]">{s.n}</span>{s.title}
          </Link>
        ))}
      </div>
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-navy-900">Step {n}. {step.title} <span className="text-slate-400 font-normal text-base">- {date}</span></h1>
          <p className="text-sm text-slate-500 mt-1">{step.question} {children}</p>

        </div>
        <div className="flex gap-2 shrink-0">
          {prev && <Link to={prev.to} className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs border border-slate-200 text-slate-600 bg-white"><ArrowLeft className="w-3.5 h-3.5" />{prev.title}</Link>}
          {next ? <Link to={next.to} className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs bg-blue-600 text-white">Next: {next.title}<ArrowRight className="w-3.5 h-3.5" /></Link>
            : <Link to="/" className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs bg-blue-600 text-white">Back to Today</Link>}
        </div>
      </div>
    </div>
  );
}

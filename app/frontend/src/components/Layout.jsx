import React, { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import Sidebar from './Sidebar';
import DemoResend from './DemoResend';
import { CalendarDays, HelpCircle } from 'lucide-react';

const NO_DATE_ROUTES = ['/reference', '/dashboard'];

function DatabricksIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 2L2 7.5V16.5L12 22L22 16.5V7.5L12 2ZM12 4.2L19.2 8.1L12 12L4.8 8.1L12 4.2ZM4 9.6L11.5 13.7V19.8L4 15.7V9.6ZM12.5 19.8V13.7L20 9.6V15.7L12.5 19.8Z" />
    </svg>
  );
}

export default function Layout({ children, dates, selectedDate, onDateChange }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const showDate = !NO_DATE_ROUTES.includes(pathname);
  const [workspaceUrl, setWorkspaceUrl] = useState('');

  useEffect(() => {
    fetch('/api/workspace-url')
      .then(r => r.json())
      .then(d => setWorkspaceUrl(d.url || ''))
      .catch(() => {});
  }, []);

  const databricksOneUrl = workspaceUrl ? `${workspaceUrl}/one` : '#';

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <header className="h-14 bg-white border-b border-slate-200 flex items-center justify-between px-6 shrink-0">
          <div className="flex items-center gap-2">
            {showDate ? (
              <>
                <CalendarDays className="w-4 h-4 text-slate-400" />
                <span className="text-sm text-slate-500">As-of date:</span>
                <select
                  value={selectedDate}
                  onChange={(e) => onDateChange(e.target.value)}
                  className="text-sm font-semibold text-navy-900 bg-slate-50 border border-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {dates.map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </select>
              </>
            ) : (
              <span className="text-sm text-slate-400">Liquidity Risk Reporting Platform</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-400">ENT001 + ENT002 + ENT003 | 6G</span>
            <DemoResend />
            <a
              href={databricksOneUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="w-8 h-8 rounded-full flex items-center justify-center bg-red-600 text-white hover:bg-red-700 transition-colors shadow-sm"
              title="Databricks One"
            >
              <DatabricksIcon className="w-4 h-4" />
            </a>
            <button
              onClick={() => navigate('/reference')}
              className="w-8 h-8 rounded-full flex items-center justify-center bg-amber-500 text-white hover:bg-amber-600 transition-colors shadow-sm"
              title="User Guide"
            >
              <HelpCircle className="w-4 h-4" />
            </button>
            <div className="w-8 h-8 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs font-bold">
              NB
            </div>
          </div>
        </header>
        {/* Content */}
        <main className="flex-1 overflow-y-auto bg-slate-50 p-6">
          {children}
        </main>
      </div>
    </div>
  );
}

import React from 'react';
import DashboardEmbed from '../components/DashboardEmbed';

// The Dashboard module: the FR 2052a AI/BI dashboard with its own tabs -
// source to report, data quality, rule coverage and validation, the Fed tables, then the adjustments made in the app.
export default function SourceToReport() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-navy-900">Dashboard</h1>
        <p className="text-sm text-slate-500 mt-1">Databricks AI/BI dashboard on Delta - every record, any volume. Tabs: Source to Report, Data quality,
          Rule coverage and validation, FR 2052a tables, Adjustments.</p>
      </div>
      <DashboardEmbed page="data" title="FR 2052a Liquidity Reporting" height={2300} />
    </div>
  );
}

import React from 'react';

const num = (v, d = 4) => (v == null || v === '' ? '--' : isNaN(v) ? String(v) : parseFloat(v).toLocaleString('en-US', { maximumFractionDigits: d }));
const when = (t) => (t ? String(t).replace('T', ' ').slice(0, 19) : '');
const ENV_COLOR = { Volume: 'bg-amber-100 text-amber-800', Lakeflow: 'bg-sky-100 text-sky-800', Silver: 'bg-slate-200 text-slate-800',
  Gold: 'bg-yellow-100 text-yellow-800', Lakebase: 'bg-emerald-100 text-emerald-800', Delta: 'bg-orange-100 text-orange-800' };
const envCls = (e) => ENV_COLOR[Object.keys(ENV_COLOR).find((k) => (e || '').includes(k))] || 'bg-slate-100 text-slate-700';

function KV({ obj }) {
  return (
    <div className="grid grid-cols-3 gap-x-4 gap-y-0.5 text-[11px]">
      {Object.entries(obj || {}).map(([k, v]) => <div key={k}><span className="text-slate-400">{k.replace(/_/g, ' ')}: </span>{num(v)}</div>)}
    </div>
  );
}

// One position, step by step: CSV row -> Bronze -> DQ gate -> calculation layer and enrichment -> PID -> reporting-entity scope
// -> FR 2052a table record (6G report key) -> validation -> its element in the 6G XML file -> Lakebase for the app.
export default function PositionJourney({ j, onTrace }) {
  return (
    <div className="space-y-0">
      <div className="text-sm text-slate-600 mb-3">Position <span className="font-mono font-semibold">{j.position_id}</span> (source record {j.record_id}) -&gt;
        FR 2052a <b>{j.product_id}</b> in table {j.table.table_code} {j.table.table_name}, 6G report type <span className="font-mono">{j.table.xml_report_type}</span></div>
      {j.steps.map((s, i) => (
        <div key={s.n} className="flex gap-3">
          <div className="flex flex-col items-center">
            <div className="w-7 h-7 rounded-full bg-navy-900 text-white text-xs font-semibold flex items-center justify-center shrink-0">{s.n}</div>
            {i < j.steps.length - 1 && <div className="w-px flex-1 bg-slate-300 my-1" />}
          </div>
          <div className="flex-1 bg-white rounded-xl border border-slate-200 shadow-sm p-3 mb-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-semibold text-navy-900">{s.stage}</span>
              <span className={`text-[10px] px-2 py-0.5 rounded-full ${envCls(s.environment)}`}>{s.environment}</span>
              <span className="ml-auto text-[11px] text-slate-400">{when(s.when)}</span>
            </div>
            <div className="text-[11px] text-slate-500 mt-0.5"><span className="font-mono text-slate-700">{s.where}</span> - {s.by}</div>
            {s.detail && <div className="mt-2"><KV obj={s.detail} /></div>}
            {s.enrichment && (
              <table className="w-full text-[11px] mt-2"><thead className="text-slate-400"><tr><th className="text-left w-48">Field</th><th className="text-left w-48">Value</th><th className="text-left">How it was derived</th></tr></thead>
                <tbody>{s.enrichment.map((e) => <tr key={e.field} className="border-t border-slate-100"><td className="py-0.5">{e.field.replace(/_/g, ' ')}</td><td className="font-medium">{num(e.value)}</td><td className="text-slate-500">{e.how}</td></tr>)}</tbody></table>
            )}
            {s.candidates && (
              <div className="mt-2 text-[11px]"><div className="text-slate-400">Rules for this product type, in order (the first match wins):</div>
                {s.candidates.map((c) => <div key={c.rule_id} className={`font-mono ${c.rule_id === s.detail.rule ? 'text-emerald-700 font-semibold' : 'text-slate-500'}`}>
                  {c.priority}. {c.condition_sql} -&gt; {c.product_id}{c.rule_id === s.detail.rule ? '   <- matched' : ''}</div>)}</div>
            )}
            {s.scope && (
              <table className="w-full text-[11px] mt-2"><thead className="text-slate-400"><tr><th className="text-left">Reporting entity</th><th className="text-left">Scope</th><th className="text-left">Relationship</th><th className="text-left">Internal counterparty</th></tr></thead>
                <tbody>{s.scope.map((e) => <tr key={e.reporting_entity} className="border-t border-slate-100"><td className="py-0.5">{e.reporting_entity} {e.entity_name}</td><td>{e.scope_type}</td>
                  <td className="font-medium">{e.relationship}</td><td>{e.internal_counterparty || ''}</td></tr>)}
                  {s.eliminated.map((e) => <tr key={`x${e.reporting_entity}`} className="border-t border-slate-100 text-slate-500"><td className="py-0.5">{e.reporting_entity}</td><td colSpan={3}>eliminated - intercompany with {e.counterparty_legal_entity}</td></tr>)}</tbody></table>
            )}
            {s.filed && s.filed.map((e) => (
              <div key={e.reporting_entity} className="mt-2 border-t border-slate-100 pt-2">
                <div className="text-xs"><b>{e.reporting_entity}</b>: this position contributes <b>{num(e.contribution)}</b> to a record of {e.record_count} position(s)
                  {e.adjustment_ids ? `, adjusted by ${e.adjustment_ids}` : ''} - reportID {e.report_id}
                  <button className="ml-2 text-blue-700 hover:underline" onClick={() => onTrace(e.record_key)}>trace this record</button></div>
                <div className="text-[11px] text-slate-400 mt-1">6G report key (records with the same values are summed):</div><KV obj={e.report_key} />
                <div className="text-[11px] text-slate-400 mt-1">Amounts filed:</div><KV obj={e.amounts} />
                {e.xml && <>
                  <div className="text-[11px] text-slate-400 mt-1">In the 6G file <span className="font-mono">{e.xml_file?.file_name}</span>:</div>
                  <pre className="text-[10px] bg-slate-900 text-slate-100 rounded p-2 overflow-x-auto">{e.xml}</pre></>}
              </div>
            ))}
          </div>
        </div>
      ))}
      {j.also?.lcr?.length > 0 && (
        <div className="ml-10 bg-white rounded-xl border border-slate-200 shadow-sm p-3 text-[11px]">
          <div className="text-sm font-semibold text-navy-900 mb-1">Also used in the LCR (12 CFR 249) - reg_lcr.calculation_detail, reported as S.L.6</div>
          {j.also.lcr.map((l, k) => <div key={k}>{l.entity_id}: {l.rule_id} {l.rule_name} ({l.flow_direction}{l.hqla_level ? `, ${l.hqla_level}` : ''}) - {num(l.amount_usd, 2)} x {num(l.rate)} = {num(l.weighted_amount_usd, 2)} USD mm</div>)}
        </div>
      )}
    </div>
  );
}

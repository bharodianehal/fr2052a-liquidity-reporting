import React, { useState, useEffect, useMemo } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { api } from '../api';
import { Package, Users, Shield, Clock, List, Building2, ShieldCheck, Scale, Boxes, GitBranch, Contact, BookOpen } from 'lucide-react';

const pct = (p) => (p.value != null && p.value !== '' ? `${(parseFloat(p.value) * 100).toFixed(0)}%` : '--');
const mono = { fontFamily: 'monospace', fontSize: '11px', color: '#475569' };

const TABS = [
  { key: 'products', label: 'Products (PIDs)', icon: Package },
  { key: 'standard-products', label: 'Standard Product Types', icon: Boxes },
  { key: 'source-products', label: 'Bank Product Codes', icon: Boxes },
  { key: 'pid-rules', label: 'PID Derivation Rules', icon: GitBranch },
  { key: 'customers', label: 'Customer Master', icon: Contact },
  { key: 'counterparties', label: 'Counterparties', icon: Users },
  { key: 'collateral', label: 'Collateral Classes', icon: Shield },
  { key: 'maturity-buckets', label: 'Maturity Buckets', icon: Clock },
  { key: 'bank-holidays', label: 'Business Calendar', icon: Clock },
  { key: 'header', label: 'Reporting Entities', icon: Building2 },
  { key: 'legal-entities', label: 'Legal Entities', icon: Building2 },
  { key: 'fed-psv', label: 'Fed Post-Submission Checks', icon: ShieldCheck },
  { key: 'templates', label: 'Report Templates', icon: List },
  { key: 'stwf-rules', label: 'FR Y-15 STWF (App. VII)', icon: Scale },
  { key: 'firm-schema', label: 'Firm Include XSD', icon: List },
  { key: 'dq-rules', label: 'DQ Rules', icon: ShieldCheck },
  { key: 'lcr-rules', label: 'LCR Appendix VI', icon: Scale },
  { key: 'validation-rules', label: 'Fed 6G BR Rules', icon: ShieldCheck },
  { key: 'spec-rules', label: 'Appendix Rules', icon: BookOpen },
];

const COL_DEFS = {
  products: [
    { field: 'product_id', headerName: 'PID', cellStyle: { fontWeight: 600, color: '#1e40af' } },
    { field: 'table_code', headerName: 'Table' },
    { field: 'product_name', headerName: 'Name (6G XSD)' },
    { field: 'instructions_name', headerName: 'Instructions wording' },
    { field: 'table_name', headerName: 'Table name' },
    { field: 'definition_page', headerName: 'Page', type: 'numericColumn' },
  ],
  'standard-products': [
    { field: 'source_system', headerName: 'Source system' },
    { field: 'standard_product_type', headerName: 'Standard product type', cellStyle: { fontWeight: 600 } },
    { field: 'description', headerName: 'Description' },
    { field: 'candidate_product_ids', headerName: 'Possible PIDs', cellStyle: { color: '#1e40af' } },
    { field: 'requires_customer', headerName: 'Needs customer' },
    { field: 'requires_collateral', headerName: 'Needs collateral' },
  ],
  'source-products': [
    { field: 'source_system', headerName: 'Source system' },
    { field: 'source_product_code', headerName: 'Bank product code', cellStyle: { fontWeight: 600 } },
    { field: 'standard_product_type', headerName: 'Standard product type', cellStyle: { color: '#1e40af' } },
    { field: 'description', headerName: 'Description' },
    { field: 'approved_on', headerName: 'Approved on (new codes)' },
  ],
  'pid-rules': [
    { field: 'rule_id', headerName: 'Rule' },
    { field: 'standard_product_type', headerName: 'Standard product type' },
    { field: 'priority', headerName: 'Order', type: 'numericColumn' },
    { field: 'condition_sql', headerName: 'Condition (SQL)', cellStyle: mono },
    { field: 'product_id', headerName: 'PID', cellStyle: { fontWeight: 600, color: '#1e40af' } },
    { field: 'rationale', headerName: 'Rationale' },
  ],
  customers: [
    { field: 'customer_id', headerName: 'Customer' },
    { field: 'customer_name', headerName: 'Name' },
    { field: 'counterparty', headerName: 'FR 2052a Counterparty' },
    { field: 'gsib_parent', headerName: 'G-SIB' },
    { field: 'affiliate_legal_entity_id', headerName: 'Affiliate legal entity' },
    { field: 'has_relationship', headerName: 'Other relationship' },
    { field: 'approved_on', headerName: 'Approved on' },
    { field: 'approved_by', headerName: 'Approved by' },
  ],
  'legal-entities': [
    { field: 'legal_entity_id', headerName: 'Legal entity', cellStyle: { fontWeight: 600 } },
    { field: 'legal_name', headerName: 'Name' },
    { field: 'entity_type', headerName: 'Type' },
    { field: 'parent_legal_entity_id', headerName: 'Parent' },
    { field: 'country', headerName: 'Country' },
  ],
  'fed-psv': [
    { field: 'check_id', headerName: 'Check', cellStyle: { fontWeight: 600 } },
    { field: 'check_name', headerName: 'Name' },
    { field: 'description', headerName: 'What it tests' },
    { field: 'approach', headerName: 'Approach' },
    { field: 'severity', headerName: 'Severity' },
  ],
  templates: [
    { field: 'report_code', headerName: 'Report' },
    { field: 'template_version', headerName: 'Template', cellStyle: { fontWeight: 600 } },
    { field: 'activated_on', headerName: 'Activated' },
    { field: 'retired_on', headerName: 'Retired' },
  ],
  'stwf-rules': [
    { field: 'rule_id', headerName: 'Rule' },
    { field: 'stwf_item', headerName: 'FR Y-15 G item', cellStyle: { fontWeight: 600 } },
    { field: 'item_name', headerName: 'Item' },
    { field: 'product_ids', headerName: 'FR 2052a PIDs', cellStyle: { color: '#1e40af' } },
    { field: 'condition_sql', headerName: 'Condition (SQL)', cellStyle: mono },
    { field: 'tier_weight', headerName: 'Weight' },
  ],
  counterparties: [
    { field: 'counterparty', headerName: 'Counterparty (6G XSD value)' },
    { field: 'counterparty_category', headerName: 'Category' },
    { field: 'is_financial', headerName: 'Financial sector' },
    { field: 'source', headerName: 'Source' },
  ],
  collateral: [
    { field: 'collateral_class', headerName: 'Class' },
    { field: 'description', headerName: 'Description' },
    { field: 'hqla_level', headerName: 'HQLA Level' },
    { field: 'lcr_haircut_pct', headerName: 'LCR Haircut', valueFormatter: pct },
    { field: 'is_hqla', headerName: 'HQLA?' },
  ],
  'bank-holidays': [
    { field: 'holiday_date', headerName: 'Date' },
    { field: 'holiday_name', headerName: 'Holiday' },
    { field: 'calendar', headerName: 'Calendar' },
  ],
  'maturity-buckets': [
    { field: 'bucket_seq', headerName: '#', type: 'numericColumn' },
    { field: 'bucket_label', headerName: 'Bucket' },
    { field: 'maturity_start', headerName: '6G maturityStart', cellStyle: mono },
    { field: 'maturity_end', headerName: '6G maturityEnd', cellStyle: mono },
    { field: 'day_start', headerName: 'Day from', type: 'numericColumn' },
    { field: 'day_end', headerName: 'Day to', type: 'numericColumn' },
    { field: 'bucket_type', headerName: 'Type' },
    { field: 'is_within_30d', headerName: 'Within 30d' },
  ],
  header: [
    { field: 'entity_id', headerName: 'Entity' },
    { field: 'entity_name', headerName: 'Name' },
    { field: 'scope_type', headerName: 'Scope' },
    { field: 'root_legal_entity_id', headerName: 'Root legal entity' },
    { field: 'entity_type', headerName: 'Entity type' },
    { field: 'lcr_standalone', headerName: 'Standalone LCR' },
    { field: 'fed_category', headerName: 'Fed Category' },
    { field: 'is_gsib', headerName: 'G-SIB' },
    { field: 'tailoring_profile', headerName: 'IV-b profile' },
    { field: 'reporter_ticker', headerName: 'Reporter' },
    { field: 'listing_exchange', headerName: 'Exchange (MIC)' },
    { field: 'report_scope', headerName: 'reportScope' },
    { field: 'primary_timing', headerName: 'Primary due' },
    { field: 'reduced_timing', headerName: 'Reduced due' },
  ],
  'firm-schema': [
    { field: 'list_name', headerName: 'Firm XSD type' },
    { field: 'value', headerName: 'Value', cellStyle: { fontWeight: 600 } },
    { field: 'description', headerName: 'Description' },
  ],
  'dq-rules': [
    { field: 'rule_id', headerName: 'Rule' },
    { field: 'rule_name', headerName: 'Name' },
    { field: 'rule_category', headerName: 'Category' },
    { field: 'severity', headerName: 'Severity' },
    { field: 'quarantine', headerName: 'Quarantine' },
    { field: 'fail_predicate', headerName: 'Fails when (SQL)', cellStyle: mono },
  ],
  'lcr-rules': [
    { field: 'rule_id', headerName: 'Rule' },
    { field: 'rule_section', headerName: '12 CFR 249' },
    { field: 'rule_name', headerName: 'Name' },
    { field: 'flow_direction', headerName: 'Direction' },
    { field: 'applicable_product_ids', headerName: 'Products' },
    { field: 'counterparty_category_condition', headerName: 'Counterparty category' },
    { field: 'collateral_hqla_condition', headerName: 'Collateral' },
    { field: 'maturity_condition', headerName: 'Maturity' },
    { field: 'outflow_rate', headerName: 'Outflow %', valueFormatter: pct },
    { field: 'inflow_rate', headerName: 'Inflow %', valueFormatter: pct },
    { field: 'rule_priority', headerName: 'Priority' },
  ],
  'validation-rules': [
    { field: 'rule_id', headerName: 'Rule ID' },
    { field: 'schedule_code', headerName: 'Table' },
    { field: 'xml_element', headerName: 'XML element' },
    { field: 'rule_category', headerName: 'Category' },
    { field: 'enforced_by', headerName: 'Checked by' },
    { field: 'severity', headerName: 'Severity' },
    { field: 'validation_rule', headerName: 'Fed business requirement' },
  ],
  'spec-rules': [
    { field: 'rule_id', headerName: 'Rule' },
    { field: 'appendix', headerName: 'Source' },
    { field: 'table_code', headerName: 'Table' },
    { field: 'rule_name', headerName: 'Rule' },
    { field: 'check_type', headerName: 'Check' },
    { field: 'severity', headerName: 'Severity' },
    { field: 'params', headerName: 'Parameters', cellStyle: mono },
  ],
};

export default function Configuration({ embedded }) {
  const [activeTab, setActiveTab] = useState('products');
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const autoSize = useMemo(() => ({ type: 'fitCellContents' }), []);

  useEffect(() => {
    setLoading(true);
    api.getConfig(activeTab).then(setData).catch(console.error).finally(() => setLoading(false));
  }, [activeTab]);

  return (
    <div className="space-y-4">
      <div>
        {!embedded && <h1 className="text-xl font-bold text-navy-900">Configuration</h1>}
        <p className="text-sm text-slate-500 mt-1">FR 2052a specification (Instructions + Fed 6G XSD / Business Requirements), the firm's source-to-PID mapping and master data, and the rule sets</p>
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap gap-1 bg-white rounded-xl border border-slate-200 p-1.5">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
              activeTab === tab.key ? 'bg-navy-900 text-white' : 'text-slate-600 hover:bg-slate-100'
            }`}
          >
            <tab.icon className="w-3.5 h-3.5" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Data Grid */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between">
          <span className="text-sm font-medium text-slate-600">{data.length} records</span>
          <span className="text-xs text-slate-400">6G | reference_data/*.csv, loaded by notebook 01</span>
        </div>
        <div className="ag-theme-alpine" style={{ height: 520 }}>
          <AgGridReact
            rowData={data}
            columnDefs={COL_DEFS[activeTab] || []}
            defaultColDef={{ sortable: true, filter: true, resizable: true }}
            autoSizeStrategy={autoSize}
            animateRows
            pagination
            paginationPageSize={100}
            enableCellTextSelection
            loading={loading}
          />
        </div>
      </div>
    </div>
  );
}

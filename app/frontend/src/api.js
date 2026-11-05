const BASE = '/api';

async function fetchJson(url) {
  const res = await fetch(`${BASE}${url}`);
  if (!res.ok) {
    const detail = await res.json().then((j) => j.detail).catch(() => null);
    throw new Error(detail || `API error: ${res.status}`);
  }
  return res.json();
}

async function postJson(url, body) {
  const res = await fetch(`${BASE}${url}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().then((j) => j.detail).catch(() => null);
    throw new Error(detail || `API error: ${res.status}`);
  }
  return res.json();
}

export const api = {
  // Pipeline runs (fr2052a-daily job)
  runPipeline: (date, scope) => postJson('/pipeline/run', { date, scope }),
  getPipelineRuns: () => fetchJson('/pipeline/runs'),
  demoReset: () => postJson('/demo/reset', {}),
  demoResetStatus: () => fetchJson('/demo/reset'),
  demoResendOptions: () => fetchJson('/demo/resend'),

  // Core
  getDates: () => fetchJson('/dates'),

  // Gold Tables - FR 2052a

  // Combined filing view

  // DQ

  // LCR

  // Validation & Recon
  getValidation: (date) => fetchJson(`/validation/${date}`),

  // FR 2052a data tables
  getTables: () => fetchJson('/tables'),
  getTableRecords: (date, table) => fetchJson(`/filing/${date}/table/${table}`),

  // 6G submission, business review and sign-off
  getSubmission: (date, run) => fetchJson(`/submission/${date}${run ? `?run=${run}` : ''}`),
  reviewSubmission: (date, action, note) => postJson(`/submission/${date}/review`, { action, note }),
  getSubmissionHistory: () => fetchJson('/submission-history'),
  downloadSubmissionFile: (date, fileType, run) => `${BASE}/submission/${date}/file/${fileType}${run ? `?run=${run}` : ''}`,

  // PID derivation and LCR detail

  // Configuration - reference data (spec, firm and rules)
  getConfig: (name) => fetchJson(`/config/${name}`),

  // Reporting workbench (v9)
  wbCalendar: () => fetchJson('/wb/calendar'),
  wbLineageRecord: (date, key) => fetchJson(`/wb/lineage/${date}/record/${key}`),
  wbLineagePosition: (date, id) => fetchJson(`/wb/lineage/${date}/position/${encodeURIComponent(id)}`),
  wbLineageSource: (date, id) => fetchJson(`/wb/lineage/${date}/source/${encodeURIComponent(id)}`),
  wbCollect: (date) => fetchJson(`/wb/collect/${date}`),
  wbCollectRecord: (date, id) => fetchJson(`/wb/collect/${date}/record/${encodeURIComponent(id)}`),
  wbCorrectTarget: (date, t) => fetchJson(`/wb/correct/${date}?${t.record_key ? `record_key=${t.record_key}` : `position_id=${encodeURIComponent(t.position_id)}`}`),
  wbPostCorrection: (date, body) => postJson(`/wb/corrections/${date}`, body),
  wbRevalidate: (date) => postJson(`/wb/revalidate/${date}`, {}),
  wbGenerate: (date) => postJson(`/wb/generate/${date}`, {}),
  wbGenerateStatus: (date) => fetchJson(`/wb/generate/${date}`),
  wbRevalidateStatus: (date) => fetchJson(`/wb/revalidate/${date}`),
  wbRerunFromDq: (date) => postJson(`/wb/rerun-from-dq/${date}`, {}),
  wbRerunStatus: (date) => fetchJson(`/wb/rerun-from-dq/${date}`),
  wbResend: (date, feed) => postJson(`/wb/collect/${date}/resend/${feed}`, {}),
  wbEnrich: (date) => fetchJson(`/wb/enrich/${date}`),
  wbDqQueue: (date) => fetchJson(`/wb/dq/${date}/queue`),
  wbDqSuggest: (date, id) => fetchJson(`/wb/dq/${date}/suggest/${encodeURIComponent(id)}`),
  wbDqResolve: (date, body) => postJson(`/wb/dq/${date}/resolve`, body),
  wbValQueue: (date) => fetchJson(`/wb/validate/${date}/queue`),
  wbValSuggest: (date, rule, key) => fetchJson(`/wb/validate/${date}/suggest?rule_id=${encodeURIComponent(rule)}&item_key=${encodeURIComponent(key)}`),
  wbValResolve: (date, body) => postJson(`/wb/validate/${date}/resolve`, body),
  agBreaks: (date) => fetchJson(`/wb/agents/${date}/breaks`),
  agBreak: (id) => fetchJson(`/wb/agents/break/${encodeURIComponent(id)}`),
  agDecide: (id, body) => postJson(`/wb/agents/break/${encodeURIComponent(id)}/decide`, body),
  agRerun: (id) => postJson(`/wb/agents/break/${encodeURIComponent(id)}/rerun`, {}),
  agItem: (date, kind, ref) => fetchJson(`/wb/agents/${date}/item?kind=${kind}&ref=${encodeURIComponent(ref)}`),
  agBulk: (date, body) => postJson(`/wb/agents/${date}/approve-bulk`, body),
  agReview: (date) => fetchJson(`/wb/agents/${date}/review`),
  agAudit: (date, who) => fetchJson(`/wb/agents/${date}/audit?who=${who}`),
  agSourceFixes: (date) => fetchJson(`/wb/agents/${date}/source-fixes`),
  agAuditExportUrl: (date, audience) => `/api/wb/agents/${date}/audit/export?audience=${encodeURIComponent(audience)}`,
  agToday: (date, entity = 'ENT001') => fetchJson(`/wb/agents/${date}/today?entity=${entity}`),
  agAsk: (id, question) => postJson(`/wb/agents/break/${encodeURIComponent(id)}/ask`, { question }),
  agSpotCheck: (id, verdict, note) => postJson(`/wb/agents/break/${encodeURIComponent(id)}/spot-check`, { verdict, note }),
  agReleaseMemo: (date, refresh = false) => fetchJson(`/wb/agents/${date}/release-memo${refresh ? '?refresh=true' : ''}`),
  agLearning: () => fetchJson('/wb/agents/learning'),
  agAccuracy: () => fetchJson('/wb/agents/accuracy'),
  wbLcrReference: () => fetchJson('/wb/lcr/reference'),
  wbLcrMapping: (date, entity) => fetchJson(`/wb/lcr/${date}/mapping?entity=${entity}`),
  wbLcrCalculation: (date, entity) => fetchJson(`/wb/lcr/${date}/calculation?entity=${entity}`),
  wbLcrExplain: (date, entity) => fetchJson(`/wb/lcr/${date}/explain?entity=${entity}`),
  wbLcrDisclosure: (start, end, entity) => fetchJson(`/wb/lcr/disclosure?start=${start}&end=${end}&entity=${entity}`),
  wbLcrDraft: (start, end, entity) => fetchJson(`/wb/lcr/disclosure/draft?start=${start}&end=${end}&entity=${entity}`),
  wbLcrDraftGenerate: (start, end, entity) => postJson('/wb/lcr/disclosure/draft', { start, end, entity }),
  wbLcrSection: (body) => postJson('/wb/lcr/disclosure/section', body),
  wbLcrExportUrl: (start, end, entity) => `/api/wb/lcr/disclosure/export?start=${start}&end=${end}&entity=${entity}`,
  wbLcrRulePositions: (date, rule, entity, page) => fetchJson(`/wb/lcr/${date}/rule/${encodeURIComponent(rule)}/positions?entity=${entity}&page=${page}`),
  wbEnrichQueue: (date) => fetchJson(`/wb/enrich/${date}/queue`),
  wbEnrichPids: (date, code) => fetchJson(`/wb/enrich/${date}/table/${code}/pids`),
  wbEnrichPositions: (date, code, pid, page) => fetchJson(`/wb/enrich/${date}/positions?code=${code}&pid=${encodeURIComponent(pid)}&page=${page}`),
  wbToday: (date) => fetchJson(`/wb/today/${date}`),
  wbAi: (date, kind) => fetchJson(`/wb/ai/${date}${kind ? `?kind=${kind}` : ''}`),
  wbAiDecide: (id, decision, note, edits) => postJson(`/wb/ai/${id}/decide`, { decision, note, edits }),
  wbEntitySummary: (date) => fetchJson(`/wb/entity-summary/${date}`),
  wbVariance: (date, anomaliesOnly) => fetchJson(`/wb/variance/${date}${anomaliesOnly ? '?anomalies_only=true' : ''}`),
  wbMetadata: (q) => fetchJson(`/wb/metadata?q=${encodeURIComponent(q || '')}`),

  // Downloads
  downloadExcel: (date) => `${BASE}/filing/${date}/download-excel`,
};

import React, { useState } from 'react';
import { ChevronRight, ChevronLeft, HelpCircle, ListChecks, Inbox, Tags, ShieldCheck, ClipboardCheck, Send, MessageSquare, GitBranch, BookOpen, History } from 'lucide-react';

// The guide follows the analyst's day: Today, the five steps, then the pages used at any time.
const PAGES = [
  {
    title: 'Start here',
    icon: HelpCircle,
    content: [
      'This app produces the Federal Reserve **FR 2052a** liquidity report (6G XML) for one as-of date at a time, for three reporting entities in one file: **ENT001** Acme Financial Holdings (consolidated), **ENT002** Acme National Bank (solo) and **ENT003** Acme Securities (broker-dealer, solo). All data is synthetic.',
      '**Your day, in five steps** (left menu, top to bottom):',
      '- **1. Collect** - did every source file arrive and load into Bronze?',
      '- **2. Data quality** - which records pass the rules; fix and put back the quarantined ones.',
      '- **3. PID enrichment** - counterparty, currency, product (PID) and the other FR 2052a attributes; AI suggestions for anything new.',
      '- **4. Validate** - every rule exception resolved (AI fix, manual fix, or explain a warning) and every comment the AI drafted for the Fed accepted, edited or rejected; the report tables as filed.',
      '- **5. Generate 6G & release** - nothing to review: the 6G files are generated from the fixed report, checked against the Fed XSD, approved, and a second person marks them submitted.',
            '**Pick the as-of date** at the top of the page. **Today** shows the five steps for that date with what is open in each, and tells you where to go next.',
      '**AI maker, human checker:** the agents find every break and make the change - with the evidence (Instructions, 12 CFR 249, Vector Search), an independent rule check and the LCR effect; you decide each item **on its step page only** (accept the AI fix, fix it yourself, exclude / explain, or return it to the agent with a reason) - the agent\'s sources, rule check, LCR effect and "ask about this item" sit under the AI-suggested fix. **Today > Where it stands** says what was done and what is left per step; **Today > The run** shows the maturity river (a ! opens the item on its step page); **Audit** is the trail and the examiner export.',
      '**Any time:** Genie, Dashboard, Lineage, Reference (PID dictionary, reference data, this guide), Audit and History.',
      '**Liquidity risk:** LCR - the Liquidity Coverage Ratio module: an AI explanation of the day\'s LCR move and the LCR dashboard; the quarterly disclosure (35-line template + AI-drafted sections to review, approve and export); the calculation step by step (with the maturity mismatch add-on); the data mapping; the regulatory reference.',
      '**Rules of the house:** the PID rules, calculations and checks are authoritative. AI only proposes; nothing changes the filing until a person accepts it and the day is re-run. Adjustments and sign-off need a second person (four eyes).',
    ],
  },
  {
    title: 'Today',
    icon: ListChecks,
    content: [
      'The home page: a checklist of the five steps for the chosen as-of date, with the Primary due date (T+2 business days) and the Reduced due date.',
      'Each step shows a state:',
      '- **Done** - nothing open.',
      '- **Look at it** - warnings or items to review, nothing blocking.',
      '- **Action needed** - something blocks the filing or needs a decision.',
      '- **Not run yet** - the day (or this part of it) has not been processed.',
      'The blue bar names the next step to work on. **Run the day / Re-run the day** starts the pipeline for this date (about 20 minutes): use it after you fix source data, accept AI proposals or approve adjustments, so the next reporting run picks them up.',
    ],
  },
  {
    title: '1. Collect',
    icon: Inbox,
    content: [
      'Each source system lands a daily CSV extract in the landing volume; Lakeflow loads it into its Bronze table (raw.<feed>) exactly as received.',
      'For each feed: the file received, the records loaded, the trailing 5-day median and the completeness flag - below 90% of the median WARNING, below 80% or missing FAIL. Chase the source owner for any incomplete feed.',
    ],
  },
  {
    title: '2. Data quality',
    icon: ShieldCheck,
    content: [
      'The first layer of Silver. Every data quality rule (SQL in reference.rules_dq), pass or fail. Records that pass move to conformed.source_position; records failing an ERROR rule are quarantined.',
      'Click a failed rule to see the records that failed it, then a record to see every value as received and the rule it broke (with the rule SQL).',
      '**Fix a quarantined record:** change the field(s), give the reason, save. The fix is logged (who, when, before -> after, why) and applied before the rules on the next run - Bronze stays as received. **Re-run from data quality** puts the fixed record back and redoes everything after it (about 20 minutes).',
    ],
  },
  {
    title: '3. PID enrichment',
    icon: Tags,
    content: [
      'Silver organised like the report: Inflows, Outflows and Supplemental, one tile per FR 2052a table with its positions, the positions with an issue and the positions held out.',
      'Each position shows what the enrichment set - product type, the PID rule that matched and the PID, customer and counterparty, G-SIB, collateral class, maturity date and bucket, currency, insured - and any issue: no product (PID), counterparty missing or not allowed for the product, unknown currency, collateral class missing, maturity bucket missing.',
      '**Fix:** accept or edit the AI suggestions for what the masters do not know yet (new counterparties / customers, new product codes, PID exceptions), or **Correct** a position directly. **Re-run enrichment** applies accepted master data.',
    ],
  },
  {
    title: '4. Validate',
    icon: ClipboardCheck,
    content: [
      '**Exceptions:** a work queue - one item per failing record of every FAIL / WARNING rule (FR 2052a Instructions, Fed 6G business rules, the Fed\'s 14 post-submission checks, the reconciliations). Filter by state, rule or search; go one by one. Each item shows the rule, the failure and the **AI-suggested fix** (a position correction, or an explanation): **Accept AI fix**, **Fix manually** (the positions behind the record - the most granular data held), or **Explain & keep** (warnings). Then **Re-run validation** until no exception remains (about 10 minutes; a new reporting run).',
      '**Browse report tables:** the FR 2052a as the Federal Reserve structures it, per reporting entity; each table exactly as filed, the Instructions\' fields in order.',
    ],
  },
  {
    title: '5. Generate 6G & release',
    icon: Send,
    content: [
      '**Progress:** Generated -> Valid against the Fed XSD -> Approved -> Submitted.',
      '**6G files:** the Primary, Reduced (month-end) and Comment XML of the latest run, validated against the Fed XSD, with downloads for the submission.',
      '**Sign-off:** approve the READY FOR REVIEW reporting run (for a BLOCKED run: fix and re-run, or request an override someone else approves); a different person marks it submitted.',
      '**Comments for the Fed:** accept or edit the AI-drafted S.C comments; accepted comments go into the next run\'s Comment file.',
    ],
  },
  {
    title: 'Dashboard & Lineage',
    icon: GitBranch,
    content: [
      '**Dashboard** - the Databricks AI/BI dashboard; the tabs follow the analyst\'s questions (as-of date and entity in its filters):',
      '- **Source to Report** - pick a day and a source feed (deposits, loans, securities, derivatives, funding, finance) to see every record at every step:',
      '- **1. Source records** - exactly as the source system sent them, every field, with the file they arrived in and when.',
      '- **2. Data quality check** - which records passed and which were held back, and by which rule.',
      '- **3. Enriched positions** - each record split into its FR 2052a parts (e.g. insured / uninsured) with counterparty, collateral, maturity and its FR 2052a product (PID) and the rule that classified it.',
      '- **4. Positions by reporting entity** - how the consolidated BHC, the bank and the broker-dealer each report the position.',
      '- **5. Reported FR 2052a records** - the records of the 6G file the positions are added up into.',
      '- **Data quality** - do I have all the data and is it right: feeds complete, records vs expected, records rejected, reconciliation breaks; received vs expected per feed; the issues to act on.',
      '- **Rule coverage and validation** - did every record get its PID from a rule (classified %, positions and amount without a rule, new customers / codes awaiting a decision; per table; the records without a rule and what is missing), and did the report pass every check (checks passed, blocking failures, warnings not yet explained, 6G files valid; by source; the checks not passing and where each stands).',
      '- **FR 2052a tables** - as the Fed prescribes: section -> table -> PID -> reported record -> the positions behind it.',
      '- **Adjustments** - every change made in the app, as of the last pipeline run.',
      'It is a Databricks dashboard reading the data directly, so it works at any volume; filter and sort any column.',
      '**Lineage** - follow one position (e.g. DEP-2026-02-27-00001#INS) step by step from its source file to its element in the 6G file, with every enrichment and how it was derived; paste a source record id to pick its parts, or a reported record key to trace it back to its positions and source records.',
    ],
  },
  {
    title: 'Genie',
    icon: MessageSquare,
    content: [
      'One place to ask about the filing in plain English - for example "is the filing ready to sign off?", "why did O.D move?", "top 10 counterparties by O.D outflows for ENT001".',
      'Genie answers from the FR 2052a Genie space: the governed Unity Catalog metric views (reported amounts, inflows and outflows, 30-day flows, LCR, HQLA, checks) and the detail tables (positions, variance, runs, AI suggestions). Every answer shows the SQL it ran and its result table, with suggested follow-ups; follow-up questions continue the same conversation.',
      'Genie reads and explains; it never approves, posts or submits. For free exploration with the SQL visible, use the link on the page to open the Genie space in Databricks. In Databricks, Genie One also has two FR 2052a skills: the daily filing review and the variance explainer.',
    ],
  },
  {
    title: 'Reference & History',
    icon: BookOpen,
    content: [
      '**PID dictionary** - every FR 2052a product ID with its 6G name, the Instructions page and the derivation rules that assign it. The FR 2052a has no MDRM codes; MDRM appears only for the FR Y-15 Schedule G items computed from 2052a data.',
      '**Reference data & rules** - reporting and legal entities, product types and codes, PID rules, customer master, counterparties, collateral classes, maturity buckets, the firm include XSD values, DQ / LCR / 6G / appendix rules, the Fed post-submission checks, report templates and the STWF rules.',
      '**History** - every as-of date with its run and sign-off state (click a day to open it in Today), and the sign-off and pipeline audit trail.',
    ],
  },
];

export default function UserGuide({ embedded }) {
  const [page, setPage] = useState(0);
  const current = PAGES[page];
  const Icon = current.icon;

  return (
    <div className="h-full flex flex-col max-h-[calc(100vh-5rem)]">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center shadow-lg shadow-amber-200">
            <HelpCircle className="w-5 h-5 text-white" />
          </div>
          <div>
            {!embedded && <h1 className="text-xl font-bold text-navy-900">User Guide</h1>}
            <p className="text-xs text-slate-500">FR 2052a Liquidity Risk Platform</p>
          </div>
        </div>
        <span className="text-xs text-slate-400">
          Page {page + 1} of {PAGES.length}
        </span>
      </div>

      {/* Content */}
      <div className="flex-1 bg-white rounded-xl border border-slate-200 shadow-sm flex flex-col overflow-hidden">
        {/* Page Nav */}
        <div className="flex border-b border-slate-100 overflow-x-auto">
          {PAGES.map((p, i) => {
            const PIcon = p.icon;
            return (
              <button
                key={i}
                onClick={() => setPage(i)}
                className={`flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium whitespace-nowrap transition-colors border-b-2 ${
                  i === page
                    ? 'border-amber-500 text-amber-700 bg-amber-50/50'
                    : 'border-transparent text-slate-500 hover:text-slate-700 hover:bg-slate-50'
                }`}
              >
                <PIcon className="w-3.5 h-3.5" />
                {p.title}
              </button>
            );
          })}
        </div>

        {/* Page Content */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="max-w-4xl mx-auto">
            {/* Title */}
            <div className="flex items-center gap-3 mb-4">
              <div className={`w-8 h-8 rounded-lg bg-amber-100 flex items-center justify-center`}>
                <Icon className="w-4 h-4 text-amber-600" />
              </div>
              <h2 className="text-lg font-bold text-navy-900">{current.title}</h2>
            </div>

            {/* Screenshot */}
            {current.img && (
              <div className="mb-5 rounded-lg border border-slate-200 overflow-hidden shadow-sm">
                <img
                  src={current.img}
                  alt={current.title}
                  className="w-full"
                  onError={(e) => { e.target.style.display = 'none'; }}
                />
              </div>
            )}

            {/* Text content */}
            <div className="space-y-2.5">
              {current.content.map((line, i) => {
                const formatted = line
                  .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                  .replace(/\u2014/g, '\u2014');
                const isBullet = line.startsWith('- ');
                return isBullet ? (
                  <div key={i} className="flex gap-2 ml-4 text-sm text-slate-700 leading-relaxed">
                    <span className="text-slate-400 shrink-0">&bull;</span>
                    <span dangerouslySetInnerHTML={{ __html: formatted.slice(2) }} />
                  </div>
                ) : (
                  <p key={i} className="text-sm text-slate-700 leading-relaxed" dangerouslySetInnerHTML={{ __html: formatted }} />
                );
              })}
            </div>
          </div>
        </div>

        {/* Footer nav */}
        <div className="flex items-center justify-between px-6 py-3 border-t border-slate-100 bg-slate-50/50">
          <button
            onClick={() => setPage(Math.max(0, page - 1))}
            disabled={page === 0}
            className="flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-700 disabled:opacity-30 transition-colors"
          >
            <ChevronLeft className="w-4 h-4" /> Previous
          </button>
          <div className="flex gap-1">
            {PAGES.map((_, i) => (
              <button
                key={i}
                onClick={() => setPage(i)}
                className={`w-2 h-2 rounded-full transition-colors ${i === page ? 'bg-amber-500' : 'bg-slate-300 hover:bg-slate-400'}`}
              />
            ))}
          </div>
          <button
            onClick={() => setPage(Math.min(PAGES.length - 1, page + 1))}
            disabled={page === PAGES.length - 1}
            className="flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-700 disabled:opacity-30 transition-colors"
          >
            Next <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>

    </div>
  );
}

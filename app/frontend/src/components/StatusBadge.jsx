import React from 'react';

const styles = {
  PASS: 'badge-pass',
  COMPLIANT: 'badge-pass',
  VALIDATED: 'badge-pass',
  SUCCESS: 'badge-pass',
  FAIL: 'badge-fail',
  FAILED: 'badge-fail',
  'NON-COMPLIANT': 'badge-fail',
  ERROR: 'badge-fail',
  WARNING: 'badge-warning',
  CONDITIONAL: 'badge-warning',
  REVIEW: 'badge-review',
  EXPECTED: 'badge-review',
};

export default function StatusBadge({ status }) {
  const cls = styles[status] || 'badge-review';
  return <span className={cls}>{status}</span>;
}

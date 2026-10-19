import React from 'react';
import { AlertTriangle } from 'lucide-react';

export default function NoticeBanner() {
  return (
    <div className="institutional-banner" role="alert">
      <AlertTriangle size={18} style={{ flexShrink: 0 }} />
      <div>
        <strong>Institutional & Synthetic Corpus Notice:</strong> This assistant generates responses strictly based on ingested documents and is <strong>not an official or legally binding source of institutional decisions</strong>. All underlying documents (e.g. KVIT) are <strong>synthetic demonstration data</strong> created for benchmarking and portfolio evaluation.
      </div>
    </div>
  );
}

import React from 'react';
import { X, FileText, Calendar, Shield, Layers, FileCheck } from 'lucide-react';

export default function DocumentDetailModal({ document, onClose }) {
  if (!document) return null;

  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <FileText size={20} color="var(--brand-blue)" />
            <h3 id="modal-title">{document.title}</h3>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={onClose} aria-label="Close modal">
            <X size={18} />
          </button>
        </div>

        <div className="modal-body">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
            <div className="card" style={{ padding: '1rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-muted)', fontSize: '0.78rem', marginBottom: '0.25rem' }}>
                <FileCheck size={16} />
                <span>FILE NAME</span>
              </div>
              <div style={{ fontWeight: '600', fontFamily: 'var(--font-mono)', fontSize: '0.88rem' }}>
                {document.file_name}
              </div>
            </div>

            <div className="card" style={{ padding: '1rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-muted)', fontSize: '0.78rem', marginBottom: '0.25rem' }}>
                <Calendar size={16} />
                <span>EFFECTIVE DATE</span>
              </div>
              <div style={{ fontWeight: '600', fontSize: '0.88rem' }}>
                {document.effective_date}
              </div>
            </div>

            <div className="card" style={{ padding: '1rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-muted)', fontSize: '0.78rem', marginBottom: '0.25rem' }}>
                <Layers size={16} />
                <span>STRUCTURE</span>
              </div>
              <div style={{ fontWeight: '600', fontSize: '0.88rem' }}>
                {document.total_pages} Pages • {document.total_chunks} Chunks
              </div>
            </div>

            <div className="card" style={{ padding: '1rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-muted)', fontSize: '0.78rem', marginBottom: '0.25rem' }}>
                <Shield size={16} />
                <span>STATUS & LINEAGE</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.2rem' }}>
                <span className={`badge ${document.status === 'active' ? 'badge-success' : 'badge-neutral'}`}>
                  {document.status}
                </span>
                {document.supersedes && (
                  <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                    Supersedes: <code>{document.supersedes}</code>
                  </span>
                )}
              </div>
            </div>
          </div>

          <div>
            <h4 style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Authorized Roles (RBAC)
            </h4>
            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              {document.allowed_roles.map((role) => (
                <span key={role} className="badge badge-info" style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>
                  {role}
                </span>
              ))}
            </div>
          </div>

          <div className="alert-box alert-info" style={{ fontSize: '0.82rem' }}>
            <span>
              🔒 <strong>Retrieval Security Note:</strong> This policy document is only surfaced to queries when the user's active role matches one of the authorized roles above. Version-aware filtering ensures active policies take precedence over superseded policies.
            </span>
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

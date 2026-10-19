import React from 'react';
import { CheckCircle, AlertCircle, Info, X } from 'lucide-react';

export default function Toast({ message, type = 'info', onClose }) {
  if (!message) return null;

  const icons = {
    success: <CheckCircle size={18} color="#10b981" />,
    error: <AlertCircle size={18} color="#ef4444" />,
    info: <Info size={18} color="#3b82f6" />,
  };

  return (
    <div
      className={`toast-notification toast-${type}`}
      role="status"
      aria-live="polite"
      style={{
        position: 'fixed',
        bottom: '24px',
        right: '24px',
        backgroundColor: 'var(--bg-surface)',
        color: 'var(--text-primary)',
        padding: '0.85rem 1.25rem',
        borderRadius: 'var(--radius-md)',
        boxShadow: 'var(--shadow-lg)',
        border: '1px solid var(--border-subtle)',
        borderLeft: `4px solid ${type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : '#3b82f6'}`,
        display: 'flex',
        alignItems: 'center',
        gap: '0.75rem',
        zIndex: 100,
        animation: 'fadeIn 200ms ease-out',
        maxWidth: '400px',
      }}
    >
      {icons[type] || icons.info}
      <span style={{ fontSize: '0.88rem', fontWeight: 500, flex: 1 }}>{message}</span>
      {onClose && (
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}
          aria-label="Dismiss toast"
        >
          <X size={15} />
        </button>
      )}
    </div>
  );
}

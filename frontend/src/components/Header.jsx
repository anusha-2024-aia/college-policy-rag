import React from 'react';
import { Menu, Shield, Wifi, WifiOff } from 'lucide-react';
import { formatRoleName, SUPPORTED_ROLES } from '../utils/roles';

export default function Header({
  activeTab,
  userRole,
  setUserRole,
  isBackendOnline,
  toggleMobileSidebar,
  onRoleChange,
}) {
  const titles = {
    dashboard: {
      title: 'Policy Intelligence Dashboard',
      subtitle: 'Find authoritative evidence, understand policy changes, and explore institutional guidance.',
    },
    ask: {
      title: 'Ask Policy',
      subtitle: 'Query academic regulations, course syllabi, and administrative handbooks with verifiable citations.',
    },
    documents: {
      title: 'Document Library',
      subtitle: 'Explore indexed policies, effective dates, document versions, and access classifications.',
    },
    evaluations: {
      title: 'Evaluation & Benchmarks',
      subtitle: 'Compare retrieval configurations and inspect measured answer-quality safeguards.',
    },
    system: {
      title: 'System Information',
      subtitle: 'Technical architecture, verification pipeline, and security boundaries.',
    },
  };

  const current = titles[activeTab] || titles.dashboard;

  const handleSelectRole = (e) => {
    const newRole = e.target.value;
    setUserRole(newRole);
    if (onRoleChange) onRoleChange(newRole);
  };

  return (
    <header className="app-header">
      <div className="header-left">
        <button
          className="mobile-menu-toggle"
          onClick={toggleMobileSidebar}
          aria-label="Toggle navigation menu"
          type="button"
        >
          <Menu size={22} />
        </button>
        <div className="page-title-badge">
          <h2>{current.title}</h2>
          <span>{current.subtitle}</span>
        </div>
      </div>

      <div className="header-right">
        {/* Simulated Access Role Widget with explicit 'Simulated role' label */}
        <div
          className="role-selector-widget"
          title="Simulated role selector for testing document visibility across permission boundaries."
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
            <Shield size={14} color="var(--brand-blue)" />
            <label htmlFor="role-select">Simulated role:</label>
          </div>
          <select
            id="role-select"
            className="role-select"
            value={userRole}
            onChange={handleSelectRole}
            aria-label="Simulated user access role"
          >
            {SUPPORTED_ROLES.map((r) => (
              <option key={r} value={r}>
                {formatRoleName(r)}
              </option>
            ))}
          </select>
        </div>

        {/* Live Backend Connection Status Indicator */}
        <div
          className="system-health-badge"
          title={
            isBackendOnline
              ? 'FastAPI backend is responsive and operational (HTTP 200 OK).'
              : 'FastAPI backend is unreachable. Verify backend server is active.'
          }
        >
          {isBackendOnline ? (
            <Wifi size={14} color="#10b981" />
          ) : (
            <WifiOff size={14} color="#ef4444" />
          )}
          <span className={`health-dot ${isBackendOnline ? 'online' : 'offline'}`} />
          <span style={{ color: isBackendOnline ? 'var(--text-secondary)' : '#ef4444', fontWeight: 600 }}>
            {isBackendOnline ? 'API Connected' : 'API Offline'}
          </span>
        </div>
      </div>
    </header>
  );
}

import React from 'react';
import {
  LayoutDashboard,
  MessageSquareText,
  FolderArchive,
  BarChart3,
  Cpu,
  Sun,
  Moon,
  ShieldCheck,
  ChevronLeft,
  ChevronRight,
  BookMarked
} from 'lucide-react';
import { formatRoleName } from '../utils/roles';

export default function Sidebar({
  activeTab,
  setActiveTab,
  isDark,
  toggleTheme,
  userRole,
  isMobileOpen,
  closeMobileSidebar,
  isCollapsed,
  toggleCollapse,
}) {
  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'ask', label: 'Ask Policy', icon: MessageSquareText },
    { id: 'documents', label: 'Document Library', icon: FolderArchive },
    { id: 'evaluations', label: 'Evaluations', icon: BarChart3 },
    { id: 'system', label: 'How it works', icon: Cpu },
  ];

  const handleNavClick = (id) => {
    setActiveTab(id);
    if (closeMobileSidebar) closeMobileSidebar();
  };

  return (
    <aside
      className={`app-sidebar ${isMobileOpen ? 'open' : ''} ${isCollapsed ? 'collapsed' : ''}`}
      aria-label="Main Navigation"
      style={{
        width: isCollapsed ? '78px' : 'var(--sidebar-width)',
        transition: 'width var(--transition-normal), transform var(--transition-normal)',
      }}
    >
      <div className="sidebar-header" style={{ justifyContent: isCollapsed ? 'center' : 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
          <div className="brand-logo-badge" title="Policy Intelligence Assistant" aria-hidden="true">
            <BookMarked size={22} />
          </div>
          {!isCollapsed && (
            <div className="brand-info">
              <h1>Policy Intelligence</h1>
              <p>Assistant</p>
            </div>
          )}
        </div>

        {/* Desktop Collapse Toggle */}
        <button
          className="sidebar-collapse-btn desktop-only"
          onClick={toggleCollapse}
          title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          type="button"
        >
          {isCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
        </button>
      </div>

      <nav className="sidebar-nav" aria-label="Main Navigation">
        <ul className="sidebar-nav-list" role="list">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <li key={item.id} className="sidebar-nav-item">
                <button
                  onClick={() => handleNavClick(item.id)}
                  className={`nav-link ${isActive ? 'active' : ''}`}
                  aria-current={isActive ? 'page' : undefined}
                  title={isCollapsed ? item.label : undefined}
                  type="button"
                  style={{
                    justifyContent: isCollapsed ? 'center' : 'flex-start',
                    padding: isCollapsed ? '0.75rem 0' : '0.75rem 1rem',
                  }}
                >
                  <Icon size={20} style={{ flexShrink: 0 }} />
                  {!isCollapsed && <span className="nav-label">{item.label}</span>}
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="sidebar-footer">
        {!isCollapsed && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#94a3b8', fontSize: '0.78rem' }}>
            <ShieldCheck size={16} color="#60a5fa" style={{ flexShrink: 0 }} />
            <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              Role: <strong style={{ color: '#ffffff' }}>{formatRoleName(userRole)}</strong>
            </span>
          </div>
        )}

        <button
          onClick={toggleTheme}
          className="theme-toggle-btn"
          aria-label={`Switch to ${isDark ? 'light' : 'dark'} mode`}
          title={`Switch to ${isDark ? 'light' : 'dark'} mode`}
          type="button"
          style={{ justifyContent: isCollapsed ? 'center' : 'space-between' }}
        >
          {!isCollapsed && <span>{isDark ? 'Light Theme' : 'Dark Theme'}</span>}
          {isDark ? <Sun size={16} /> : <Moon size={16} />}
        </button>
      </div>
    </aside>
  );
}

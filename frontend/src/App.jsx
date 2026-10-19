import React, { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import NoticeBanner from './components/NoticeBanner';
import Toast from './components/Toast';
import DashboardPage from './pages/DashboardPage';
import AssistantPage from './pages/AssistantPage';
import DocumentsPage from './pages/DocumentsPage';
import EvaluationPage from './pages/EvaluationPage';
import AboutPage from './pages/AboutPage';
import { checkBackendHealth } from './services/api';

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [userRole, setUserRole] = useState(() => {
    return localStorage.getItem('policy_rag_role') || 'student';
  });
  const [isDark, setIsDark] = useState(() => {
    return localStorage.getItem('policy_rag_theme') === 'dark';
  });
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isBackendOnline, setIsBackendOnline] = useState(true);
  const [isMobileOpen, setIsMobileOpen] = useState(false);

  // Toast notification state
  const [toast, setToast] = useState(null);

  const showToast = (message, type = 'info') => {
    setToast({ message, type });
    setTimeout(() => {
      setToast(null);
    }, 4000);
  };

  // Sync role to localStorage
  const handleRoleChange = (newRole) => {
    setUserRole(newRole);
    localStorage.setItem('policy_rag_role', newRole);
    showToast(`Access role switched to ${newRole.toUpperCase()} (Simulated)`, 'info');
  };

  // Sync theme
  useEffect(() => {
    if (isDark) {
      document.documentElement.setAttribute('data-theme', 'dark');
      localStorage.setItem('policy_rag_theme', 'dark');
    } else {
      document.documentElement.removeAttribute('data-theme');
      localStorage.setItem('policy_rag_theme', 'light');
    }
  }, [isDark]);

  const toggleTheme = () => {
    setIsDark((prev) => {
      const next = !prev;
      showToast(`Switched to ${next ? 'Dark' : 'Light'} theme`, 'info');
      return next;
    });
  };

  // Check backend health periodically
  useEffect(() => {
    let mounted = true;
    const testHealth = async () => {
      try {
        await checkBackendHealth();
        if (mounted) setIsBackendOnline(true);
      } catch {
        if (mounted) setIsBackendOnline(false);
      }
    };

    testHealth();
    const interval = setInterval(testHealth, 20000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  return (
    <div className="app-container">
      {/* Mobile backdrop */}
      {isMobileOpen && (
        <div
          className="modal-backdrop"
          style={{ zIndex: 35 }}
          onClick={() => setIsMobileOpen(false)}
        />
      )}

      {/* Persistent Navigation Sidebar */}
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        isDark={isDark}
        toggleTheme={toggleTheme}
        userRole={userRole}
        isMobileOpen={isMobileOpen}
        closeMobileSidebar={() => setIsMobileOpen(false)}
        isCollapsed={isCollapsed}
        toggleCollapse={() => setIsCollapsed(!isCollapsed)}
      />

      {/* Main Content Area */}
      <div className="main-content">
        <NoticeBanner />
        <Header
          activeTab={activeTab}
          userRole={userRole}
          setUserRole={handleRoleChange}
          isBackendOnline={isBackendOnline}
          toggleMobileSidebar={() => setIsMobileOpen(!isMobileOpen)}
          onRoleChange={handleRoleChange}
        />

        <main className="page-body" id="main-content">
          {activeTab === 'dashboard' && (
            <DashboardPage
              setActiveTab={setActiveTab}
              userRole={userRole}
            />
          )}

          {activeTab === 'ask' && (
            <AssistantPage
              userRole={userRole}
            />
          )}

          {activeTab === 'documents' && (
            <DocumentsPage
              userRole={userRole}
            />
          )}

          {activeTab === 'evaluations' && (
            <EvaluationPage
              onToast={showToast}
            />
          )}

          {activeTab === 'system' && (
            <AboutPage setActiveTab={setActiveTab} />
          )}
        </main>
      </div>

      {/* Global Toast Notification */}
      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}
    </div>
  );
}

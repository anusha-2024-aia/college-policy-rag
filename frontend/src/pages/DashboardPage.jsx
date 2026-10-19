import React, { useEffect, useState } from 'react';
import {
  MessageSquareText,
  FolderArchive,
  BarChart3,
  Layers,
  BookOpen,
  Cpu,
  ArrowRight,
  Server,
  Database,
  Activity,
  AlertCircle,
  RefreshCw,
  CheckCircle2,
} from 'lucide-react';
import { fetchSystemStats, checkBackendHealth } from '../services/api';

export default function DashboardPage({ setActiveTab, userRole }) {
  const [stats, setStats] = useState(null);
  const [apiHealth, setApiHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [statsData, healthData] = await Promise.all([
        fetchSystemStats(),
        checkBackendHealth().catch(() => null),
      ]);
      setStats(statsData);
      setApiHealth(healthData);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  return (
    <div className="dashboard-page" style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
      {/* Hero Card */}
      <div
        className="card"
        style={{
          padding: '2.25rem 2.5rem',
          background: 'linear-gradient(135deg, var(--bg-surface) 0%, var(--bg-muted) 100%)',
          borderLeft: '4px solid var(--brand-blue)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: '2rem' }}>
          <div style={{ maxWidth: '720px' }}>
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.45rem',
                padding: '0.3rem 0.85rem',
                borderRadius: 'var(--radius-full)',
                backgroundColor: 'var(--brand-accent-soft)',
                color: 'var(--brand-blue)',
                fontSize: '0.78rem',
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.04em',
                marginBottom: '1rem',
              }}
            >
              <Activity size={14} />
              <span>Grounded Institutional Policy Platform</span>
            </div>

            <h1
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: '2.1rem',
                fontWeight: 800,
                color: 'var(--text-primary)',
                lineHeight: 1.2,
                marginBottom: '0.85rem',
              }}
            >
              Policy Intelligence Dashboard
            </h1>

            <p style={{ fontSize: '1.05rem', color: 'var(--text-secondary)', lineHeight: 1.6, marginBottom: '1.75rem' }}>
              Find authoritative evidence, understand policy changes, and explore institutional guidance with verifiable citations, version conflict detection, and role-governed document boundaries.
            </p>

            <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
              <button
                className="btn btn-primary btn-lg"
                onClick={() => setActiveTab('ask')}
                id="hero-ask-btn"
              >
                <MessageSquareText size={18} />
                <span>Ask a Policy Question</span>
                <ArrowRight size={16} />
              </button>

              <button
                className="btn btn-secondary btn-lg"
                onClick={() => setActiveTab('documents')}
                id="hero-browse-docs-btn"
              >
                <FolderArchive size={18} />
                <span>Browse Documents</span>
              </button>
            </div>
          </div>

          {/* Active Context Card */}
          <div
            style={{
              minWidth: '240px',
              padding: '1.25rem 1.5rem',
              backgroundColor: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-md)',
              boxShadow: 'var(--shadow-xs)',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.65rem',
            }}
          >
            <span style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Current User Session
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
              <span className="badge badge-info" style={{ fontSize: '0.85rem', padding: '0.35rem 0.75rem' }}>
                {userRole.toUpperCase()}
              </span>
              <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>(Simulated role)</span>
            </div>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', lineHeight: 1.45, marginTop: '0.25rem' }}>
              Document retrieval and candidate passages are strictly filtered to policies permitted for <strong>{userRole}</strong> access.
            </p>
          </div>
        </div>
      </div>

      {/* Real Verified System Status Row */}
      <div className="card" style={{ padding: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.75rem' }}>
          <div>
            <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1.1rem', fontWeight: 700 }}>
              Runtime System Diagnostics
            </h3>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              Live verification signals checked against backend endpoints
            </span>
          </div>

          <button
            className="btn btn-secondary btn-sm"
            onClick={loadData}
            disabled={loading}
            title="Refresh runtime metrics from backend"
          >
            <RefreshCw size={14} className={loading ? 'spinner' : ''} />
            <span>Refresh Diagnostics</span>
          </button>
        </div>

        {error ? (
          <div className="alert-box alert-danger">
            <AlertCircle size={18} />
            <span>Unable to retrieve live diagnostics: {error}. Check if FastAPI backend is running.</span>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
            {/* API Connectivity */}
            <div style={{ padding: '1rem', backgroundColor: 'var(--bg-muted)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
                <Server size={16} color={apiHealth?.status === 'ok' ? '#10b981' : '#ef4444'} />
                <span style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>API Connectivity</span>
              </div>
              <div style={{ fontWeight: 700, fontSize: '0.95rem', color: apiHealth?.status === 'ok' ? 'var(--status-success-text)' : 'var(--status-danger-text)' }}>
                {loading ? 'Checking...' : apiHealth?.status === 'ok' ? 'Operational (HTTP 200)' : 'Unreachable'}
              </div>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                {apiHealth?.environment ? `Environment: ${apiHealth.environment}` : 'Host: API Endpoint'}
              </span>
            </div>

            {/* Database & Catalog */}
            <div style={{ padding: '1rem', backgroundColor: 'var(--bg-muted)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
                <Database size={16} color={stats?.total_docs ? '#10b981' : '#ef4444'} />
                <span style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Document Catalog</span>
              </div>
              <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>
                {loading ? 'Checking...' : stats?.total_docs ? `Connected (${stats.total_docs} docs)` : 'Empty or Unreachable'}
              </div>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>PostgreSQL + pgvector</span>
            </div>

            {/* Active Retrieval Engine */}
            <div style={{ padding: '1rem', backgroundColor: 'var(--bg-muted)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
                <Cpu size={16} color="var(--brand-blue)" />
                <span style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Active Retrieval Mode</span>
              </div>
              <div style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--brand-blue)' }}>
                {loading ? 'Detecting...' : stats?.semantic_retrieval_enabled ? 'Semantic ONNX (384d)' : 'Sparse + Dense (1536d)'}
              </div>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                Reranker: {stats?.reranker_model || 'FlashRank'}
              </span>
            </div>

            {/* LLM Synthesis Engine */}
            <div style={{ padding: '1rem', backgroundColor: 'var(--bg-muted)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
                <CheckCircle2 size={16} color="#10b981" />
                <span style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>LLM Provider</span>
              </div>
              <div style={{ fontWeight: 700, fontSize: '0.95rem', textTransform: 'uppercase' }}>
                {loading ? 'Loading...' : `${stats?.llm_provider || 'Mock'} (${stats?.llm_model || 'Offline'})`}
              </div>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Deterministic fallback enabled</span>
            </div>
          </div>
        )}
      </div>

      {/* Real Application Metrics */}
      <div>
        <h2 style={{ fontFamily: 'var(--font-display)', fontSize: '1.25rem', fontWeight: 700, marginBottom: '1rem', color: 'var(--text-primary)' }}>
          Indexed Repository Metrics
        </h2>
        <div className="stat-grid">
          <div className="stat-card">
            <div className="stat-icon-wrapper stat-icon-blue">
              <FolderArchive size={24} />
            </div>
            <div className="stat-info">
              <span className="stat-label">Indexed Documents</span>
              <span className="stat-value">{loading ? '—' : stats?.total_docs ?? 0}</span>
              <span className="stat-desc">Institutional college policy PDFs</span>
            </div>
          </div>

          <div className="stat-card">
            <div className="stat-icon-wrapper stat-icon-green">
              <Layers size={24} />
            </div>
            <div className="stat-info">
              <span className="stat-label">Indexed Chunks</span>
              <span className="stat-value">{loading ? '—' : stats?.total_chunks ?? 0}</span>
              <span className="stat-desc">500-token passages with 80-token overlap</span>
            </div>
          </div>

          <div className="stat-card">
            <div className="stat-icon-wrapper stat-icon-purple">
              <BookOpen size={24} />
            </div>
            <div className="stat-info">
              <span className="stat-label">Document Pages</span>
              <span className="stat-value">{loading ? '—' : stats?.total_pages ?? 0}</span>
              <span className="stat-desc">Parsed institutional source pages</span>
            </div>
          </div>

          <div className="stat-card">
            <div className="stat-icon-wrapper stat-icon-amber">
              <BarChart3 size={24} />
            </div>
            <div className="stat-info">
              <span className="stat-label">Golden Evaluation</span>
              <span className="stat-value" style={{ fontSize: '1.25rem', marginTop: '0.35rem' }}>33 Questions</span>
              <span className="stat-desc">KVIT benchmark ground truth</span>
            </div>
          </div>
        </div>
      </div>

      {/* How it Works: Compact 4-Step Flow */}
      <div className="card" style={{ padding: '2rem' }}>
        <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1.15rem', fontWeight: 700, marginBottom: '1.25rem' }}>
          How Policy Intelligence Works
        </h3>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1.25rem' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
              <span style={{ width: '26px', height: '26px', borderRadius: '50%', backgroundColor: 'var(--brand-blue)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: '0.8rem' }}>1</span>
              <strong style={{ fontSize: '0.95rem' }}>Question</strong>
            </div>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              User submits a policy inquiry with their active institutional access role.
            </p>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
              <span style={{ width: '26px', height: '26px', borderRadius: '50%', backgroundColor: 'var(--brand-blue)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: '0.8rem' }}>2</span>
              <strong style={{ fontSize: '0.95rem' }}>Authorized Retrieval</strong>
            </div>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              Dense embeddings and keyword search are fused via RRF, filtered strictly to authorized documents.
            </p>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
              <span style={{ width: '26px', height: '26px', borderRadius: '50%', backgroundColor: 'var(--brand-blue)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: '0.8rem' }}>3</span>
              <strong style={{ fontSize: '0.95rem' }}>Evidence & Versioning</strong>
            </div>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              FlashRank cross-encoder reranks passages; version conflicts between older and newer rules are detected.
            </p>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
              <span style={{ width: '26px', height: '26px', borderRadius: '50%', backgroundColor: 'var(--brand-blue)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: '0.8rem' }}>4</span>
              <strong style={{ fontSize: '0.95rem' }}>Grounded Answer</strong>
            </div>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              Answer is synthesized citing numbered brackets [N], or abstains honestly when evidence is insufficient.
            </p>
          </div>
        </div>
      </div>

      {/* Quick Action Navigation Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '1.25rem' }}>
        <button
          className="card"
          onClick={() => setActiveTab('ask')}
          style={{ textAlign: 'left', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '1.25rem' }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
            <MessageSquareText size={22} color="var(--brand-blue)" />
            <div>
              <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>Ask a Question</div>
              <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>Query grading, syllabi, or rules</span>
            </div>
          </div>
          <ArrowRight size={18} color="var(--text-muted)" />
        </button>

        <button
          className="card"
          onClick={() => setActiveTab('documents')}
          style={{ textAlign: 'left', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '1.25rem' }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
            <FolderArchive size={22} color="var(--brand-blue)" />
            <div>
              <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>Browse Documents</div>
              <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>Search all 20 indexed policies</span>
            </div>
          </div>
          <ArrowRight size={18} color="var(--text-muted)" />
        </button>

        <button
          className="card"
          onClick={() => setActiveTab('evaluations')}
          style={{ textAlign: 'left', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '1.25rem' }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
            <BarChart3 size={22} color="var(--brand-blue)" />
            <div>
              <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>View Evaluations</div>
              <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>Inspect Recall@K & MRR benchmarks</span>
            </div>
          </div>
          <ArrowRight size={18} color="var(--text-muted)" />
        </button>

        <button
          className="card"
          onClick={() => setActiveTab('system')}
          style={{ textAlign: 'left', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '1.25rem' }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
            <Cpu size={22} color="var(--brand-blue)" />
            <div>
              <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>System Architecture</div>
              <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>Pipeline & security notices</span>
            </div>
          </div>
          <ArrowRight size={18} color="var(--text-muted)" />
        </button>
      </div>
    </div>
  );
}

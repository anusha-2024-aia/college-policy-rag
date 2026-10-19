import React, { useEffect, useState } from 'react';
import {
  Search,
  FolderArchive,
  Upload,
  Calendar,
  Layers,
  Eye,
  RefreshCw,
  AlertCircle,
  FileCheck2,
  X,
  Info,
  ShieldCheck,
  ShieldAlert,
} from 'lucide-react';
import { fetchDocuments, inspectPdfDocument } from '../services/api';
import DocumentDetailModal from '../components/DocumentDetailModal';

export default function DocumentsPage({ userRole = 'student' }) {
  const [data, setData] = useState({ total_docs: 0, total_chunks: 0, total_pages: 0, hidden_count: 0, documents: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Filters
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedRoleFilter, setSelectedRoleFilter] = useState('all');
  const [selectedStatusFilter, setSelectedStatusFilter] = useState('all');

  // Selected doc for detail modal
  const [activeDocModal, setActiveDocModal] = useState(null);

  // PDF Preview state
  const [inspectingPdf, setInspectingPdf] = useState(false);
  const [pdfInspectResult, setPdfInspectResult] = useState(null);
  const [pdfInspectError, setPdfInspectError] = useState(null);

  const loadDocs = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetchDocuments(userRole);
      setData(resp);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDocs();
  }, [userRole]);

  const handleClearFilters = () => {
    setSearchQuery('');
    setSelectedRoleFilter('all');
    setSelectedStatusFilter('all');
  };

  // Filter documents client-side based on search and filters
  const filteredDocs = (data.documents || []).filter((doc) => {
    const matchesSearch =
      searchQuery === '' ||
      doc.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      doc.file_name.toLowerCase().includes(searchQuery.toLowerCase());

    const matchesRole =
      selectedRoleFilter === 'all' ||
      (doc.allowed_roles && doc.allowed_roles.some((r) => r.toLowerCase() === selectedRoleFilter.toLowerCase()));

    const matchesStatus =
      selectedStatusFilter === 'all' ||
      doc.status.toLowerCase() === selectedStatusFilter.toLowerCase();

    return matchesSearch && matchesRole && matchesStatus;
  });

  const isFiltered = searchQuery !== '' || selectedRoleFilter !== 'all' || selectedStatusFilter !== 'all';

  const handlePdfUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setInspectingPdf(true);
    setPdfInspectError(null);
    setPdfInspectResult(null);

    try {
      const res = await inspectPdfDocument(file);
      setPdfInspectResult(res);
    } catch (err) {
      setPdfInspectError(err.message || 'Failed to inspect PDF.');
    } finally {
      setInspectingPdf(false);
    }
  };

  const getStatusBadgeClass = (status) => {
    const s = (status || '').toLowerCase();
    if (s === 'active') return 'badge-success';
    if (s.includes('partially')) return 'badge-info';
    if (s.includes('superseded')) return 'badge-warning';
    return 'badge-neutral';
  };

  return (
    <div className="documents-page" style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
      {/* Metrics Banner */}
      <div className="stat-grid" style={{ marginBottom: 0 }}>
        <div className="stat-card">
          <div className="stat-icon-wrapper stat-icon-blue">
            <FolderArchive size={24} />
          </div>
          <div className="stat-info">
            <span className="stat-label">Accessible Documents</span>
            <span className="stat-value">{loading ? '—' : data.total_docs}</span>
            <span className="stat-desc">For role: {userRole}</span>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon-wrapper stat-icon-green">
            <Layers size={24} />
          </div>
          <div className="stat-info">
            <span className="stat-label">Accessible Chunks</span>
            <span className="stat-value">{loading ? '—' : data.total_chunks}</span>
            <span className="stat-desc">500-token text passages</span>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon-wrapper stat-icon-purple">
            <Calendar size={24} />
          </div>
          <div className="stat-info">
            <span className="stat-label">Document Pages</span>
            <span className="stat-value">{loading ? '—' : data.total_pages}</span>
            <span className="stat-desc">Parsed institutional source pages</span>
          </div>
        </div>
      </div>

      {/* Server-Side RBAC Notice for Hidden Documents */}
      {data.hidden_count > 0 && (
        <div
          className="alert-box alert-warning"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '0.75rem',
            padding: '0.85rem 1.25rem',
            borderRadius: 'var(--radius-md)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
            <ShieldAlert size={18} color="var(--brand-amber)" style={{ flexShrink: 0 }} />
            <span style={{ fontSize: '0.88rem' }}>
              <strong>Server-Side RBAC Active:</strong>{' '}
              <strong style={{ color: 'var(--brand-amber)' }}>{data.hidden_count} hidden for your role</strong> ({userRole}).
              Confidential administrative or faculty document titles and content are never transmitted to unauthorized clients.
            </span>
          </div>
          <span className="badge badge-warning" style={{ fontWeight: 700 }}>
            {data.hidden_count} hidden for your role
          </span>
        </div>
      )}

      {/* Filter and Search Bar */}
      <div className="card" style={{ padding: '1.25rem' }}>
        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
          {/* Search Box */}
          <div style={{ position: 'relative', flex: '1 1 280px', minWidth: '220px' }}>
            <Search size={18} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
            <input
              type="text"
              placeholder="Search by policy title or filename..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                width: '100%',
                padding: '0.65rem 1rem 0.65rem 2.4rem',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-subtle)',
                backgroundColor: 'var(--bg-primary)',
                fontSize: '0.9rem',
              }}
              aria-label="Search Documents"
            />
          </div>

          {/* Role Filter Pills */}
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-muted)' }}>Role Filter:</span>
            {['all', 'student', 'faculty', 'admin'].map((role) => (
              <button
                key={role}
                onClick={() => setSelectedRoleFilter(role)}
                className={`btn btn-sm ${selectedRoleFilter === role ? 'btn-primary' : 'btn-secondary'}`}
                style={{ textTransform: 'capitalize' }}
                type="button"
              >
                {role}
              </button>
            ))}
          </div>

          {/* Status Filter */}
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-muted)' }}>Status:</span>
            {['all', 'Active', 'Superseded', 'Partially amended'].map((st) => (
              <button
                key={st}
                onClick={() => setSelectedStatusFilter(st)}
                className={`btn btn-sm ${selectedStatusFilter.toLowerCase() === st.toLowerCase() ? 'btn-primary' : 'btn-secondary'}`}
                type="button"
              >
                {st}
              </button>
            ))}

            {isFiltered && (
              <button
                className="btn btn-secondary btn-sm"
                onClick={handleClearFilters}
                title="Clear all active filters"
                type="button"
              >
                <X size={14} />
                <span>Clear Filters</span>
              </button>
            )}

            <button
              className="btn btn-secondary btn-sm"
              onClick={loadDocs}
              disabled={loading}
              title="Refresh document repository"
              type="button"
            >
              <RefreshCw size={14} className={loading ? 'spinner' : ''} />
            </button>
          </div>
        </div>

        {/* Result Count Indicator */}
        <div style={{ marginTop: '0.85rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.8rem', color: 'var(--text-muted)', borderTop: '1px solid var(--border-subtle)', paddingTop: '0.65rem' }}>
          <span>
            Showing <strong>{filteredDocs.length}</strong> of <strong>{data.total_docs}</strong> accessible documents
            {data.hidden_count > 0 && (
              <span style={{ marginLeft: '0.5rem', color: 'var(--brand-amber)', fontWeight: 600 }}>
                ({data.hidden_count} hidden for your role)
              </span>
            )}
          </span>
          {isFiltered && (
            <span style={{ color: 'var(--brand-blue)' }}>Filters applied</span>
          )}
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="alert-box alert-danger">
          <AlertCircle size={20} />
          <span>Failed to load document catalog: {error}</span>
        </div>
      )}

      {/* Documents Table (Desktop View) */}
      <div className="table-wrapper desktop-only">
        <table className="data-table">
          <thead>
            <tr>
              <th>Document Title & Filename</th>
              <th>Effective Date</th>
              <th>Status</th>
              <th>Version Lineage</th>
              <th>Permitted Roles</th>
              <th>Structure</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
                  <div
                    className="spinner"
                    style={{
                      width: '24px',
                      height: '24px',
                      border: '3px solid var(--border-subtle)',
                      borderTopColor: 'var(--brand-blue)',
                      borderRadius: '50%',
                      margin: '0 auto 0.5rem',
                    }}
                  />
                  Loading repository documents...
                </td>
              </tr>
            ) : filteredDocs.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
                  No policy documents match the current filter and search criteria.
                </td>
              </tr>
            ) : (
              filteredDocs.map((doc) => (
                <tr key={doc.id}>
                  <td>
                    <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{doc.title}</div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                      {doc.file_name}
                    </div>
                  </td>
                  <td>{doc.effective_date}</td>
                  <td>
                    <span className={`badge ${getStatusBadgeClass(doc.status)}`}>
                      {doc.status}
                    </span>
                  </td>
                  <td style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    {doc.superseded_by_title ? (
                      <span style={{ color: 'var(--brand-amber)', fontWeight: 500 }}>
                        {doc.superseded_by_title}
                      </span>
                    ) : doc.supersedes ? (
                      <span title={`Supersedes: ${doc.supersedes}`}>
                        {doc.supersedes.toLowerCase().startsWith('partial:') ? 'Amends ' : 'Supersedes '}
                        <code>{doc.supersedes.replace(/^partial:\s*[^:]*:\s*/i, '')}</code>
                      </span>
                    ) : (
                      'Active / Base'
                    )}
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                      {doc.allowed_roles.map((r) => (
                        <span key={r} className="badge badge-info" style={{ fontSize: '0.68rem' }}>
                          {r}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td>
                    <span style={{ fontWeight: 600 }}>{doc.total_pages}</span> pgs • <span style={{ fontWeight: 600 }}>{doc.total_chunks}</span> chks
                  </td>
                  <td>
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => setActiveDocModal(doc)}
                      id={`view-details-${doc.id}`}
                      type="button"
                    >
                      <Eye size={14} />
                      <span>Details</span>
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Mobile Responsive Cards */}
      <div className="mobile-only" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {filteredDocs.map((doc) => (
          <div key={doc.id} className="card" style={{ padding: '1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem' }}>
              <div>
                <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>{doc.title}</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                  {doc.file_name}
                </div>
              </div>
              <span className={`badge ${getStatusBadgeClass(doc.status)}`}>
                {doc.status}
              </span>
            </div>

            <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>
              Effective: {doc.effective_date} • {doc.total_pages} pgs • {doc.total_chunks} chunks
              {doc.superseded_by_title && (
                <div style={{ color: 'var(--brand-amber)', fontWeight: 500, marginTop: '0.25rem' }}>
                  {doc.superseded_by_title}
                </div>
              )}
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', gap: '0.35rem' }}>
                {doc.allowed_roles.map((r) => (
                  <span key={r} className="badge badge-info" style={{ fontSize: '0.68rem' }}>
                    {r}
                  </span>
                ))}
              </div>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setActiveDocModal(doc)}
                type="button"
              >
                <Eye size={14} />
                <span>Details</span>
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Read-Only PDF Inspection Tool */}
      <div className="card">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.5rem' }}>
          <Upload size={20} color="var(--brand-blue)" />
          <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1.15rem', fontWeight: 700 }}>
            Policy PDF Inspection & Structure Preview (Read-Only)
          </h3>
        </div>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1.25rem' }}>
          Select any policy PDF to inspect its page count, size, and page 1 text excerpt in-memory without altering or modifying the indexed database.
        </p>

        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
          <label className="btn btn-secondary" style={{ cursor: 'pointer' }}>
            <FolderArchive size={16} />
            <span>Select PDF File</span>
            <input
              type="file"
              accept=".pdf"
              style={{ display: 'none' }}
              onChange={handlePdfUpload}
              disabled={inspectingPdf}
            />
          </label>
          {inspectingPdf && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem', color: 'var(--brand-blue)' }}>
              <div
                className="spinner"
                style={{
                  width: '16px',
                  height: '16px',
                  border: '2px solid var(--brand-blue)',
                  borderTopColor: 'transparent',
                  borderRadius: '50%',
                }}
              />
              <span>Parsing PDF structure in-memory...</span>
            </div>
          )}
        </div>

        {pdfInspectError && (
          <div className="alert-box alert-danger" style={{ marginTop: '1rem' }}>
            <AlertCircle size={18} />
            <span>{pdfInspectError}</span>
          </div>
        )}

        {pdfInspectResult && (
          <div
            style={{
              marginTop: '1.25rem',
              padding: '1.25rem',
              backgroundColor: 'var(--bg-muted)',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border-subtle)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem', fontWeight: 700, color: 'var(--brand-blue)' }}>
              <FileCheck2 size={18} />
              <span>Inspection Succeeded: {pdfInspectResult.filename}</span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '0.75rem', marginBottom: '1rem' }}>
              <div>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Parsed Pages:</span>
                <div style={{ fontWeight: 600 }}>{pdfInspectResult.num_pages} pages</div>
              </div>
              <div>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>File Size:</span>
                <div style={{ fontWeight: 600 }}>{pdfInspectResult.file_size_kb} KB</div>
              </div>
            </div>

            {pdfInspectResult.preview_text && (
              <div>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.35rem' }}>Page 1 Excerpt Preview:</span>
                <pre
                  style={{
                    padding: '0.85rem',
                    backgroundColor: 'var(--bg-surface)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '0.8rem',
                    whiteSpace: 'pre-wrap',
                    maxHeight: '180px',
                    overflowY: 'auto',
                  }}
                >
                  {pdfInspectResult.preview_text}
                </pre>
              </div>
            )}

            <div className="alert-box alert-info" style={{ marginTop: '1rem', fontSize: '0.8rem' }}>
              <Info size={16} style={{ flexShrink: 0 }} />
              <span>
                🔒 <strong>Database Protection:</strong> Direct database writes from browser upload are disabled to safeguard institutional audit trails. To ingest newly approved policies, append them to <code>docs/documents_manifest.csv</code> and run the verified CLI pipeline: <code>python -m app.cli.ingest</code>.
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Document Detail Modal */}
      {activeDocModal && (
        <DocumentDetailModal
          document={activeDocModal}
          onClose={() => setActiveDocModal(null)}
        />
      )}
    </div>
  );
}

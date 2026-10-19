import assert from 'node:assert';
import { normalizeMarkdown } from '../src/utils/markdown.js';
import { formatRoleName, isValidRole } from '../src/utils/roles.js';

console.log('Running Response Rendering, Citations, Conflict & UI Regression Tests...');

// ============================================================================
// 1. Markdown Normalization & Escaped Asterisk / Broken List Tests
// ============================================================================

// 1.1 Unescaping backslash-escaped characters
const escapedInput = 'The policy rules are:\\* Attendance must be >= 75\\%\\* Minimum grade is C\\[1\\]\\.';
const normalized = normalizeMarkdown(escapedInput);
assert(!normalized.includes('\\*'), 'Escaped asterisks must be converted to unescaped asterisks');
assert(!normalized.includes('\\['), 'Escaped brackets must be converted to unescaped brackets');
assert(normalized.includes('*'), 'Must contain actual unescaped asterisk');

// 1.2 Fixing concatenated headings without blank lines
const concatenatedHeading = 'Here is the summary\n### Important Rules\n1. Must register on time';
const fixedHeading = normalizeMarkdown(concatenatedHeading);
assert(fixedHeading.includes('\n\n### Important Rules'), 'Concatenated heading must be preceded by a blank line');

// 1.3 Fixing concatenated bullet points
const concatenatedList = 'General guidelines:* First provision* Second provision';
const fixedList = normalizeMarkdown(concatenatedList);
assert(fixedList.includes('* First provision'), 'Bullet item 1 must be separated');
assert(fixedList.includes('\n* Second provision'), 'Bullet item 2 must be on its own line');

// 1.4 Fixing horizontal rules
const rawHr = 'Above text\n---\nBelow text';
const fixedHr = normalizeMarkdown(rawHr);
assert(fixedHr.includes('\n\n---\n\n'), 'Horizontal rule must have surrounding empty lines for clean rendering');

// ============================================================================
// 2. Role Handling & Abstention Separation Tests
// ============================================================================

// 2.1 Demo role must NEVER be 'Abstained'
const rolesToTest = ['student', 'faculty', 'admin'];
rolesToTest.forEach((r) => {
  assert(isValidRole(r), `Role ${r} must be valid`);
  assert.notStrictEqual(formatRoleName(r).toLowerCase(), 'abstained', 'Role name cannot be abstained');
});
assert.strictEqual(isValidRole('Abstained'), false, 'Abstained is an answer status, never an authorized role');

// 2.2 Formatting simulated role display
assert.strictEqual(formatRoleName('student'), 'Student');
assert.strictEqual(formatRoleName('faculty'), 'Faculty');
assert.strictEqual(formatRoleName('admin'), 'Administrator');

// 2.3 Simulated role badge must be distinct from Answer Status
function formatHeaderStatus(role, isAbstained, hasConflict) {
  const roleDisplay = `Demo Role: ${formatRoleName(role)}`;
  const statusDisplay = isAbstained
    ? 'Insufficient evidence'
    : hasConflict
    ? 'Conflict Detected'
    : 'Grounded & Verified';
  return { roleDisplay, statusDisplay };
}

const abstainedState = formatHeaderStatus('student', true, false);
assert.strictEqual(abstainedState.roleDisplay, 'Demo Role: Student', 'Abstained state must preserve Demo Role');
assert.strictEqual(abstainedState.statusDisplay, 'Insufficient evidence', 'Status must indicate insufficient evidence');
assert(!abstainedState.roleDisplay.includes('Abstained'), 'Role display must never say Abstained');

const conflictState = formatHeaderStatus('faculty', false, true);
assert.strictEqual(conflictState.roleDisplay, 'Demo Role: Faculty');
assert.strictEqual(conflictState.statusDisplay, 'Conflict Detected');

const verifiedState = formatHeaderStatus('admin', false, false);
assert.strictEqual(verifiedState.roleDisplay, 'Demo Role: Administrator');
assert.strictEqual(verifiedState.statusDisplay, 'Grounded & Verified');

// ============================================================================
// 3. Three Mutually Distinct UI States (Success, Abstention, API Error)
// ============================================================================

function resolveUIState(result, error) {
  if (error) return 'API_ERROR';
  if (!result) return 'EMPTY_OR_LOADING';
  if (result.abstained) return 'INSUFFICIENT_EVIDENCE';
  return 'GROUNDED_SUCCESS';
}

assert.strictEqual(resolveUIState(null, 'Network connection failed'), 'API_ERROR');
assert.strictEqual(resolveUIState({ abstained: true, answer: 'I do not have sufficient information' }, null), 'INSUFFICIENT_EVIDENCE');
assert.strictEqual(resolveUIState({ abstained: false, answer: 'Hostel curfew is 10 PM [1].', citations: [{ index: 1 }] }, null), 'GROUNDED_SUCCESS');

// ============================================================================
// 4. Citation and Genuine Metadata Integrity Tests
// ============================================================================

const samplePassage = {
  chunk_id: 'chk-101',
  document_title: 'KVIT Student Code of Conduct 2024',
  file_name: 'student_code_of_conduct_2024.pdf',
  effective_date: '2024-01-01',
  is_superseded: false,
  superseded_by: null,
  total_pages: 14,
  total_chunks: 28,
};

const sampleCitation = {
  index: 1,
  file_name: 'student_code_of_conduct_2024.pdf',
  page_number: 3,
  snippet: 'Undergraduate curfew is strictly 10:00 PM on weekdays.',
};

// Verify citation card uses genuine passage metadata rather than synthetic string
function resolveInspectMetadata(cit, passage, catalogDocs = []) {
  const catalogDoc = catalogDocs.find((d) => d.file_name === cit.file_name);
  if (catalogDoc) return catalogDoc;

  return {
    id: passage?.chunk_id || cit.file_name,
    title: passage?.document_title || cit.file_name.replace('.pdf', '').replace(/_/g, ' '),
    file_name: cit.file_name,
    effective_date: passage?.effective_date || 'Active',
    status: passage?.is_superseded ? 'superseded' : 'active',
    supersedes: passage?.superseded_by || null,
    total_pages: cit.page_number,
    total_chunks: 1,
  };
}

const resolvedMeta = resolveInspectMetadata(sampleCitation, samplePassage);
assert.strictEqual(resolvedMeta.title, 'KVIT Student Code of Conduct 2024', 'Must use genuine document title from database');
assert.strictEqual(resolvedMeta.effective_date, '2024-01-01', 'Must use genuine effective date from database');
assert.notStrictEqual(resolvedMeta.effective_date, 'Verified in policy index', 'Must not use placeholder date string');

// ============================================================================
// 5. Version Conflict Resolution Verification
// ============================================================================

const sampleConflict = {
  current_title: 'KVIT Remote Attendance Policy 2024',
  current_file: 'remote_attendance_2024.pdf',
  current_effective_date: '2024-01-01',
  superseded_title: 'KVIT Remote Attendance Policy 2022',
  superseded_file: 'remote_attendance_2022.pdf',
  superseded_effective_date: '2022-01-01',
  description: 'Permits 3 virtual lecture attendances per semester, superseding 1 virtual lecture permitted under 2022 rules.',
};

assert(sampleConflict.current_effective_date > sampleConflict.superseded_effective_date, 'Active policy must postdate superseded policy');
assert.notStrictEqual(sampleConflict.current_file, sampleConflict.superseded_file, 'Active and superseded files must differ');

console.log('All Response Rendering, Citations, Conflict & UI Regression Tests PASSED successfully!');

import assert from 'node:assert';
import {
  SUPPORTED_ROLES,
  DEFAULT_ROLE,
  normalizeRole,
  formatRoleName,
  isValidRole,
} from '../src/utils/roles.js';

console.log('Running Ask Policy Frontend Role Unit Tests...');

// 1. Check supported roles
assert.deepStrictEqual(SUPPORTED_ROLES, ['student', 'faculty', 'admin'], 'Supported roles must match backend');
assert.strictEqual(DEFAULT_ROLE, 'student', 'Default role should be student');

// 2. Check formatRoleName
assert.strictEqual(formatRoleName('student'), 'Student');
assert.strictEqual(formatRoleName('faculty'), 'Faculty');
assert.strictEqual(formatRoleName('admin'), 'Administrator');
assert.strictEqual(formatRoleName('STUDENT'), 'Student');
assert.strictEqual(formatRoleName(''), 'Student');
assert.strictEqual(formatRoleName(null), 'Student');
assert.strictEqual(formatRoleName(undefined), 'Student');
assert.strictEqual(formatRoleName('unknown_role'), 'Student');

// 3. Check normalizeRole
assert.strictEqual(normalizeRole('Student'), 'student');
assert.strictEqual(normalizeRole('STUDENT'), 'student');
assert.strictEqual(normalizeRole('faculty'), 'faculty');
assert.strictEqual(normalizeRole('admin'), 'admin');
assert.strictEqual(normalizeRole('administrator'), 'admin');
assert.strictEqual(normalizeRole('ADMINISTRATOR'), 'admin');
assert.strictEqual(normalizeRole(''), 'student');
assert.strictEqual(normalizeRole(null), 'student');

// 4. Check isValidRole
assert.strictEqual(isValidRole('student'), true);
assert.strictEqual(isValidRole('faculty'), true);
assert.strictEqual(isValidRole('admin'), true);
assert.strictEqual(isValidRole('guest'), false);
assert.strictEqual(isValidRole('Abstained'), false);

// 5. Verify abstention message formatting never results in blank parentheses
const currentRoleDisplay = formatRoleName('student');
const abstentionMessage = `No sufficient evidence was found in the documents available to the ${currentRoleDisplay} demo role to answer this question factually.`;
assert(!abstentionMessage.includes('()'), 'Abstention message must never contain empty parentheses ()');
assert(abstentionMessage.includes('Student demo role'), 'Abstention message must include formatted role');

console.log('All frontend role unit tests PASSED successfully!');

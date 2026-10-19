/**
 * Role normalization and formatting utilities for Policy Intelligence Assistant.
 */

export const SUPPORTED_ROLES = ['student', 'faculty', 'admin'];

export const DEFAULT_ROLE = 'student';

export const ROLE_DISPLAY_NAMES = {
  student: 'Student',
  faculty: 'Faculty',
  admin: 'Administrator',
};

/**
 * Check if a raw string is a valid supported role.
 */
export function isValidRole(role) {
  if (!role) return false;
  const clean = String(role).trim().toLowerCase();
  return SUPPORTED_ROLES.includes(clean);
}

/**
 * Normalize input role to valid API role identifier ('student' | 'faculty' | 'admin').
 * Defaults to 'student' if invalid or missing.
 */
export function normalizeRole(role) {
  if (!role) return DEFAULT_ROLE;
  const clean = String(role).trim().toLowerCase();
  if (clean === 'administrator') return 'admin';
  return SUPPORTED_ROLES.includes(clean) ? clean : DEFAULT_ROLE;
}

/**
 * Return user-facing display label for a role ('Student', 'Faculty', 'Administrator').
 */
export function formatRoleName(role) {
  const norm = normalizeRole(role);
  return ROLE_DISPLAY_NAMES[norm] || 'Student';
}

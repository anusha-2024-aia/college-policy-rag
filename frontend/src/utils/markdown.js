/**
 * Markdown Utilities for Normalization, Tokenization, and Parsing.
 * Pure JavaScript - Node and Browser compatible.
 */

/**
 * Normalizes raw Markdown output from LLM/backend:
 * - Unescapes backslash-escaped characters (\*, \_, \[, \], etc.)
 * - Inserts missing line breaks between concatenated headings/lists
 * - Fixes inline concatenated bullet lists
 * - Standardizes horizontal rules
 */
export function normalizeMarkdown(text) {
  if (!text) return '';

  let normalized = String(text);

  // 1. Unescape backslash-escaped characters that LLMs frequently output
  normalized = normalized
    .replace(/\\\*/g, '*')
    .replace(/\\_/g, '_')
    .replace(/\\\[/g, '[')
    .replace(/\\\]/g, ']')
    .replace(/\\#/g, '#')
    .replace(/\\`/g, '`');

  // 2. Fix concatenated headings (e.g. "paragraph\n### Heading" without empty line)
  normalized = normalized.replace(/([^\n])\n(#{1,4}\s+[^\n]+)/g, '$1\n\n$2');

  // 3. Fix concatenated bullet lists
  normalized = normalized.replace(/([^\n*+-])\s*(\n\s*[*+-]\s+[^\n]+)/g, '$1\n\n$2');

  // 4. Fix inline concatenated list items (e.g. "Requirements: * Rule 1 * Rule 2" or "guidelines:* Rule 1* Rule 2")
  normalized = normalized.replace(/([^\n*+-])\s*([*+-]\s+[A-Z0-9])/g, '$1\n$2');

  // 5. Fix numbered lists touching preceding text
  normalized = normalized.replace(/([^\n])\n(\d+\.\s+[^\n]+)/g, '$1\n\n$2');

  // 6. Fix horizontal rules touching text
  normalized = normalized.replace(/([^\n])\n(---+|\*\*\*+|___+)\n/g, '$1\n\n$2\n\n');

  return normalized;
}

/**
 * Tokenizes a line of text into inline tokens:
 * - Code: `code`
 * - Citation reference: [1], [2], [1, 2]
 * - Bold italic: ***text*** or ___text___
 * - Bold: **text** or __text__
 * - Italic: *text* or _text_
 * - Link: [label](url)
 * - Plain text
 */
export function tokenizeInline(text) {
  if (!text) return [];

  const regex = /(`[^`]+`)|(\[\d+(?:,\s*\d+)*\])|(\*\*\*[^*]+\*\*\*)|(_{3}[^_]+_{3})|(\*\*[^*]+\*\*)|(_{2}[^_]+_{2})|(\*[^*]+\*)|(_[^_]+_)|(\[[^\]]+\]\([^)]+\))/g;

  const tokens = [];
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      tokens.push({ type: 'text', value: text.substring(lastIndex, match.index) });
    }

    const token = match[0];
    if (token.startsWith('`') && token.endsWith('`')) {
      tokens.push({ type: 'code', value: token.slice(1, -1) });
    } else if (token.startsWith('[') && /\[\d+(?:,\s*\d+)*\]/.test(token)) {
      const numbers = token.replace(/[[\]]/g, '').split(',').map((n) => parseInt(n.trim(), 10));
      tokens.push({ type: 'citation', numbers });
    } else if (token.startsWith('***') && token.endsWith('***')) {
      tokens.push({ type: 'bold_italic', value: token.slice(3, -3) });
    } else if (token.startsWith('**') && token.endsWith('**')) {
      tokens.push({ type: 'bold', value: token.slice(2, -2) });
    } else if (token.startsWith('__') && token.endsWith('__')) {
      tokens.push({ type: 'bold', value: token.slice(2, -2) });
    } else if (token.startsWith('*') && token.endsWith('*')) {
      tokens.push({ type: 'italic', value: token.slice(1, -1) });
    } else if (token.startsWith('_') && token.endsWith('_')) {
      tokens.push({ type: 'italic', value: token.slice(1, -1) });
    } else if (token.startsWith('[') && token.includes('](')) {
      const linkMatch = token.match(/\[([^\]]+)\]\(([^)]+)\)/);
      if (linkMatch) {
        tokens.push({ type: 'link', label: linkMatch[1], url: linkMatch[2] });
      } else {
        tokens.push({ type: 'text', value: token });
      }
    } else {
      tokens.push({ type: 'text', value: token });
    }

    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    tokens.push({ type: 'text', value: text.substring(lastIndex) });
  }

  return tokens;
}

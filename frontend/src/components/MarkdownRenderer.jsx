import React from 'react';
import { normalizeMarkdown } from '../utils/markdown';

// Parse inline formatting: bold, italic, inline code, and citation badges [N]
function parseInlineFormattedText(text, onCitationClick = null) {
  if (!text) return text;

  // Tokenize string by matching inline tokens:
  // - Code: `code`
  // - Citation badge: [1], [2], [1, 2]
  // - Bold italic: ***text*** or ___text___
  // - Bold: **text** or __text__
  // - Italic: *text* or _text_
  // - Markdown link: [label](url)
  const regex = /(`[^`]+`)|(\[\d+(?:,\s*\d+)*\])|(\*\*\*[^*]+\*\*\*)|(_{3}[^_]+_{3})|(\*\*[^*]+\*\*)|(_{2}[^_]+_{2})|(\*[^*]+\*)|(_[^_]+_)|(\[[^\]]+\]\([^)]+\))/g;

  const elements = [];
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    // Push preceding plain text
    if (match.index > lastIndex) {
      elements.push(text.substring(lastIndex, match.index));
    }

    const token = match[0];
    const key = `inline-${match.index}`;

    if (token.startsWith('`') && token.endsWith('`')) {
      // Inline code
      elements.push(
        <code key={key} className="markdown-inline-code">
          {token.slice(1, -1)}
        </code>
      );
    } else if (token.startsWith('[') && /\[\d+(?:,\s*\d+)*\]/.test(token)) {
      // Citation references like [1] or [1, 2]
      const numbers = token.replace(/[[\]]/g, '').split(',').map((n) => parseInt(n.trim(), 10));
      elements.push(
        <span key={key} className="citation-reference-group">
          {numbers.map((num, nidx) => (
            <button
              key={`${key}-cit-${num}-${nidx}`}
              type="button"
              className="citation-pill-badge"
              onClick={() => onCitationClick && onCitationClick(num)}
              title={`Jump to verified citation [${num}]`}
              aria-label={`Citation ${num}`}
            >
              [{num}]
            </button>
          ))}
        </span>
      );
    } else if (token.startsWith('***') && token.endsWith('***')) {
      elements.push(
        <strong key={key}>
          <em>{token.slice(3, -3)}</em>
        </strong>
      );
    } else if (token.startsWith('**') && token.endsWith('**')) {
      elements.push(
        <strong key={key} className="markdown-bold">
          {token.slice(2, -2)}
        </strong>
      );
    } else if (token.startsWith('__') && token.endsWith('__')) {
      elements.push(
        <strong key={key} className="markdown-bold">
          {token.slice(2, -2)}
        </strong>
      );
    } else if (token.startsWith('*') && token.endsWith('*')) {
      elements.push(
        <em key={key} className="markdown-italic">
          {token.slice(1, -1)}
        </em>
      );
    } else if (token.startsWith('_') && token.endsWith('_')) {
      elements.push(
        <em key={key} className="markdown-italic">
          {token.slice(1, -1)}
        </em>
      );
    } else if (token.startsWith('[') && token.includes('](')) {
      // Link [text](url)
      const linkMatch = token.match(/\[([^\]]+)\]\(([^)]+)\)/);
      if (linkMatch) {
        elements.push(
          <a
            key={key}
            href={linkMatch[2]}
            target="_blank"
            rel="noopener noreferrer"
            className="markdown-link"
          >
            {linkMatch[1]}
          </a>
        );
      } else {
        elements.push(token);
      }
    } else {
      elements.push(token);
    }

    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    elements.push(text.substring(lastIndex));
  }

  return elements.length > 0 ? elements : text;
}

export default function MarkdownRenderer({ content, onCitationClick, className = '' }) {
  if (!content) return null;

  const normalized = normalizeMarkdown(content);
  const lines = normalized.split('\n');

  const blocks = [];
  let currentList = null; // { type: 'ul' | 'ol', items: [] }
  let currentTable = null; // { headers: [], rows: [] }
  let currentCodeBlock = null; // { language: '', lines: [] }
  let currentQuote = null; // []

  const flushList = () => {
    if (currentList) {
      const ListTag = currentList.type;
      const listClass = currentList.type === 'ul' ? 'markdown-ul' : 'markdown-ol';
      blocks.push(
        <ListTag key={`list-${blocks.length}`} className={listClass}>
          {currentList.items.map((item, idx) => (
            <li key={idx} className="markdown-li">
              {parseInlineFormattedText(item, onCitationClick)}
            </li>
          ))}
        </ListTag>
      );
      currentList = null;
    }
  };

  const flushTable = () => {
    if (currentTable) {
      blocks.push(
        <div key={`table-wrapper-${blocks.length}`} className="markdown-table-wrapper">
          <table className="markdown-table">
            <thead>
              <tr>
                {currentTable.headers.map((h, idx) => (
                  <th key={idx}>{parseInlineFormattedText(h.trim(), onCitationClick)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {currentTable.rows.map((row, rIdx) => (
                <tr key={rIdx}>
                  {row.map((cell, cIdx) => (
                    <td key={cIdx}>{parseInlineFormattedText(cell.trim(), onCitationClick)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      currentTable = null;
    }
  };

  const flushQuote = () => {
    if (currentQuote) {
      blocks.push(
        <blockquote key={`quote-${blocks.length}`} className="markdown-blockquote">
          {currentQuote.map((qLine, idx) => (
            <p key={idx}>{parseInlineFormattedText(qLine, onCitationClick)}</p>
          ))}
        </blockquote>
      );
      currentQuote = null;
    }
  };

  const flushAll = () => {
    flushList();
    flushTable();
    flushQuote();
  };

  let i = 0;
  while (i < lines.length) {
    const rawLine = lines[i];
    const trimmed = rawLine.trim();

    // 1. Code Block Fence (```)
    if (trimmed.startsWith('```')) {
      if (currentCodeBlock) {
        // Close code block
        blocks.push(
          <div key={`codeblock-${blocks.length}`} className="markdown-codeblock-container">
            {currentCodeBlock.language && (
              <div className="markdown-codeblock-header">{currentCodeBlock.language}</div>
            )}
            <pre className="markdown-codeblock">
              <code>{currentCodeBlock.lines.join('\n')}</code>
            </pre>
          </div>
        );
        currentCodeBlock = null;
      } else {
        flushAll();
        const lang = trimmed.replace(/^```/, '').trim();
        currentCodeBlock = { language: lang, lines: [] };
      }
      i++;
      continue;
    }

    if (currentCodeBlock) {
      currentCodeBlock.lines.push(rawLine);
      i++;
      continue;
    }

    // 2. Empty Line -> Flush active containers
    if (!trimmed) {
      flushAll();
      i++;
      continue;
    }

    // 3. Horizontal Rule
    if (/^(---|___|\*\*\*)$/.test(trimmed)) {
      flushAll();
      blocks.push(<hr key={`hr-${blocks.length}`} className="markdown-hr" />);
      i++;
      continue;
    }

    // 4. Headings (# H1, ## H2, ### H3, #### H4)
    const headingMatch = trimmed.match(/^(#{1,4})\s+(.*)$/);
    if (headingMatch) {
      flushAll();
      const level = headingMatch[1].length;
      const headingText = headingMatch[2];
      const HeadingTag = `h${level}`;
      blocks.push(
        <HeadingTag key={`h-${blocks.length}`} className={`markdown-h${level}`}>
          {parseInlineFormattedText(headingText, onCitationClick)}
        </HeadingTag>
      );
      i++;
      continue;
    }

    // 5. Blockquote (> ...)
    if (trimmed.startsWith('>')) {
      flushList();
      flushTable();
      const quoteText = trimmed.replace(/^>\s?/, '');
      if (!currentQuote) currentQuote = [];
      currentQuote.push(quoteText);
      i++;
      continue;
    }

    // 6. Markdown Table
    // Check if line looks like | col1 | col2 |
    if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
      flushList();
      flushQuote();
      const cells = trimmed
        .slice(1, -1)
        .split('|')
        .map((c) => c.trim());

      // If next line is table separator (|---|---|)
      if (!currentTable && i + 1 < lines.length && /^\|[\s-:]+\|/.test(lines[i + 1].trim())) {
        currentTable = { headers: cells, rows: [] };
        i += 2; // Skip header and divider
        continue;
      } else if (currentTable) {
        // Avoid adding divider line as data
        if (!/^[\s-:]+$/.test(cells.join(''))) {
          currentTable.rows.push(cells);
        }
        i++;
        continue;
      }
    }

    // 7. Unordered List (*, -, +)
    const ulMatch = trimmed.match(/^[*+-]\s+(.*)$/);
    if (ulMatch) {
      flushTable();
      flushQuote();
      if (!currentList || currentList.type !== 'ul') {
        flushList();
        currentList = { type: 'ul', items: [] };
      }
      currentList.items.push(ulMatch[1]);
      i++;
      continue;
    }

    // 8. Ordered List (1., 2.)
    const olMatch = trimmed.match(/^(\d+)\.\s+(.*)$/);
    if (olMatch) {
      flushTable();
      flushQuote();
      if (!currentList || currentList.type !== 'ol') {
        flushList();
        currentList = { type: 'ol', items: [] };
      }
      currentList.items.push(olMatch[2]);
      i++;
      continue;
    }

    // 9. Standard Paragraph
    flushAll();
    blocks.push(
      <p key={`p-${blocks.length}`} className="markdown-p">
        {parseInlineFormattedText(trimmed, onCitationClick)}
      </p>
    );
    i++;
  }

  // Flush any remaining active elements
  flushAll();
  if (currentCodeBlock) {
    blocks.push(
      <pre key={`codeblock-${blocks.length}`} className="markdown-codeblock">
        <code>{currentCodeBlock.lines.join('\n')}</code>
      </pre>
    );
  }

  return <div className={`markdown-body ${className}`}>{blocks}</div>;
}

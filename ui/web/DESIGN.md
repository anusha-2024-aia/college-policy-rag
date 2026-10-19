---
name: Policy Intelligence Studio
colors:
  surface: '#faf8ff'
  surface-dim: '#d2d9f4'
  surface-bright: '#faf8ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f3ff'
  surface-container: '#eaedff'
  surface-container-high: '#e2e7ff'
  surface-container-highest: '#dae2fd'
  on-surface: '#131b2e'
  on-surface-variant: '#434655'
  inverse-surface: '#283044'
  inverse-on-surface: '#eef0ff'
  outline: '#737686'
  outline-variant: '#c3c6d7'
  surface-tint: '#0053db'
  primary: '#004ac6'
  on-primary: '#ffffff'
  primary-container: '#2563eb'
  on-primary-container: '#eeefff'
  inverse-primary: '#b4c5ff'
  secondary: '#006a61'
  on-secondary: '#ffffff'
  secondary-container: '#86f2e4'
  on-secondary-container: '#006f66'
  tertiary: '#824500'
  on-tertiary: '#ffffff'
  tertiary-container: '#a65900'
  on-tertiary-container: '#ffede1'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dbe1ff'
  primary-fixed-dim: '#b4c5ff'
  on-primary-fixed: '#00174b'
  on-primary-fixed-variant: '#003ea8'
  secondary-fixed: '#89f5e7'
  secondary-fixed-dim: '#6bd8cb'
  on-secondary-fixed: '#00201d'
  on-secondary-fixed-variant: '#005049'
  tertiary-fixed: '#ffdcc3'
  tertiary-fixed-dim: '#ffb77d'
  on-tertiary-fixed: '#2f1500'
  on-tertiary-fixed-variant: '#6e3900'
  background: '#faf8ff'
  on-background: '#131b2e'
  surface-variant: '#dae2fd'
typography:
  display-lg:
    fontFamily: Geist
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.025em
  display-lg-mobile:
    fontFamily: Geist
    fontSize: 26px
    fontWeight: '600'
    lineHeight: 34px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Geist
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Geist
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.015em
  headline-sm:
    fontFamily: Geist
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.01em
  body-lg:
    fontFamily: Geist
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 24px
    letterSpacing: -0.005em
  body-md:
    fontFamily: Geist
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22px
    letterSpacing: -0.003em
  body-sm:
    fontFamily: Geist
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: 0em
  label-lg:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
    letterSpacing: -0.01em
  label-md:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: -0.01em
  label-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0em
  code-inline:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
    letterSpacing: 0em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-desktop: 1.5rem
  margin: 1rem
  margin-desktop: 2rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1rem
  space-xl: 1.5rem
  space-2xl: 2rem
  space-3xl: 3rem
---

## Brand & Style

This design system is tailored for an enterprise-grade policy intelligence platform serving regulatory researchers, legal analysts, risk officers, and compliance engineers. The core visual identity merges the high-density utility of developer tools (Linear, GitHub, Vercel) with the rigorous clarity and institutional credibility of academic research consoles.

### Personality & Emotional Response
- **Surgical Precision:** Every border, line of metadata, and status indicator communicates mathematical certainty and rigorous provenance.
- **Intellectual Trust:** Eliminates decorative noise in favor of deep typographic rhythm, systematic categorization, and unmistakable evidence traceability.
- **Calm Velocity:** Allows analysts to rapidly audit regulatory corpora, reconcile conflicting statutes, and inspect semantic diffs without visual exhaustion.

### Visual Aesthetic
The aesthetic balances **Modern Technical Minimalism** with **Information-Dense Structured Utilities**:
- **Backgrounds:** Warm off-white surfaces (`#F8FAFC` to `#FFFFFF`) that offer optical comfort during prolonged analysis while preserving high contrast against slate structural elements.
- **Dividers & Boundaries:** Crisp, 1px structural hair-lines establishing clean modular grids.
- **Functional Semantics:** Purpose-driven functional accents—evidence verification teal, conflict amber, and critical regulatory infraction crimson—surfaced strictly within badges, status dots, diff gutters, and metric callouts.

## Colors

The color palette is built around an analytical hierarchy where color communicates state, provenance, and delta, rather than mere decoration.

### Functional Palette Structure
- **Primary (`#2563EB`):** High-precision royal blue used for active selections, interactive links, primary actions, focused form borders, and primary navigation states.
- **Secondary / Evidence Verified (`#0D9488`):** Deep emerald teal designating validated statutes, authenticated citations, verified source provenance, and confidence score thresholds (≥ 95%).
- **Tertiary / Conflict & Delta (`#D97706`):** Amber ochre dedicated to version diffs, conflicting statutory interpretations, pending legal revisions, and system cautions.
- **Neutral / Text & Structure (`#0F172A`):** Deep slate-black providing uncompromising legibility across micro-copy, document titles, tabular rows, and raw markdown renderings.
- **Critical Infraction / Error (`#DC2626`):** Strict crimson reserved for non-compliance violations, failed integrity checks, deprecations, and destructive operations.

### Surface Tones & Structural Borders
- **Canvas Base:** `#F8FAFC` (Slate 50) creates an anti-glare foundation.
- **Surface Elevation 1 (Cards, Tables, Panels):** `#FFFFFF` (Pure White) providing absolute contrast against the slate canvas.
- **Surface Inset / Code Backings:** `#F1F5F9` (Slate 100) for nested metadata, citation quotes, and tokenized syntax.
- **Hairline Borders:** `#E2E8F0` (Slate 200) for component frames; `#CBD5E1` (Slate 300) for interactive control borders.

## Typography

The typographic system utilizes **Geist** for structural headlines and reading bodies, paired with **JetBrains Mono** for technical artifacts, regulatory section numbers, diff tags, version identifiers, and confidence indicators.

### Typographic Hierarchy & Usage
- **Display & Headings:** Set in Geist Semibold with tight negative tracking (`-0.025em` to `-0.01em`) to create compact, authoritative page titles and module headers without consuming excessive vertical space.
- **Body Text:** Geist Regular calibrated at `14px` (`body-md`) with an intentional `22px` line-height for sustained analytical reading of dense regulatory clauses and policy briefs.
- **Monospace Elements:** JetBrains Mono is strictly applied to:
  - Clause numbering (e.g., `§ 404.12(b)`)
  - Commit hashes, version semantic tags (`v2.4.1-rc3`), and timestamps (`2024-10-24T14:32Z`)
  - Confidence metric percentages (`98.4% MATCH`)
  - Data table numerical alignments (always tabular/tabular-nums enabled)

## Layout & Spacing

The layout model is driven by dense, information-rich workflows modeled on developer consoles and split-screen document readers.

### Structural Shell & Grids
- **Primary Workbench Layout:** A three-panel CSS Grid architecture:
  - **Left Rail (Fixed 240px–280px):** Document tree, index, query filters.
  - **Center Panel (Flexible 1fr, min 560px):** Primary document reader, parsed statute diff, or query generation console.
  - **Right Inspector (Fixed 320px–380px):** Metadata, cited sources, conflicting rules, and audit trail logs.
- **Responsive Adaptations:**
  - **Desktop (≥ 1280px):** Full three-pane visibility with synchronized scrolling.
  - **Tablet (768px – 1279px):** Left rail collapses to an icon sidebar (48px); Right inspector converts to an overlay sheet or collapsible tab.
  - **Mobile (< 768px):** Single-column stacked layout; views switch through a top-level segmented control (`Document`, `Provenance`, `Audit`).

### Rhythm & Density Principles
- The baseline grid is built around an uncompromising 4px metric (`0.25rem` = 4px).
- Internal component paddings prioritize high density: table cells utilize `0.5rem` (`space-sm`) vertical padding and `0.75rem` (`space-md`) horizontal padding to maximize data display per viewport.
- Card containers and inspectors employ `1rem` (`space-lg`) internal gutters with 1px border dividers to establish rigid visual anchors.

## Elevation & Depth

To emphasize clarity and eliminate visual ambiguity, the design system minimizes deep dropshadows in favor of **Tonal Layering** combined with **Crisp Hairline Outlines**.

### Elevation Philosophy
1. **Level 0 (Canvas Base):** Filled with `#F8FAFC`. Zero elevation, zero shadow.
2. **Level 1 (Cards, Table Containers, Left/Right Shelves):** Background `#FFFFFF`, encased with a 1px solid `#E2E8F0` border. Ambient shadow is imperceptible: `0 1px 2px 0 rgba(15, 23, 42, 0.04)`.
3. **Level 2 (Interactive Flyouts, Autocomplete, Popovers):** Background `#FFFFFF`, border 1px solid `#CBD5E1`, with a focused directional shadow: `0 4px 6px -1px rgba(15, 23, 42, 0.08), 0 2px 4px -2px rgba(15, 23, 42, 0.04)`.
4. **Level 3 (Modal Dialogs & Critical Regulatory Diffs):** Background `#FFFFFF`, border 1px solid `#94A3B8`, with deep containment shadow: `0 20px 25px -5px rgba(15, 23, 42, 0.12), 0 8px 10px -6px rgba(15, 23, 42, 0.04)`. Paired with a 20% `#0F172A` backdrop scrim.
5. **Level Inset (Code Blocks, Citation Blocks, Previews):** Background `#F1F5F9`, border 1px solid `#E2E8F0` with no shadow, creating an etched, tactile indentation into the parent container.

## Shapes

The design system adopts a **Soft (Level 1)** geometric standard. This geometry mirrors the technical discipline of development environments—avoiding bubbly, consumer-centric radii while softening harsh 0px brutalism to preserve human ergonomics.

### Boundary Tokens & Form Logic
- **Base Geometry (`rounded` / 4px):** Applied to form inputs, buttons, inline tags, data table cell selections, and monospace badges.
- **Container Geometry (`rounded-lg` / 8px):** Applied to structured cards, modal dialogs, flyout popovers, and main document reader containers.
- **Nested Geometry (`rounded-xl` / 12px):** Reserved exclusively for root viewport panels or outer application shells when framed within floating desktop clients.
- **Pill Exceptions (`rounded-full`):** Strictly restricted to circular status indicators, avatar initials, and binary counter tags (e.g., notification counts).

## Components

### 1. Buttons
- **Primary:** Background `#2563EB`, text `#FFFFFF`, border 1px solid `#1D4ED8`. Hover: `#1D4ED8`. Height: 32px (compact), 36px (regular). Font: Geist Medium 13px. Focus ring: 2px `#2563EB` offset 2px.
- **Secondary / Outline:** Background `#FFFFFF`, text `#0F172A`, border 1px solid `#CBD5E1`. Hover: `#F8FAFC`, border `#94A3B8`.
- **Tertiary / Ghost:** Background transparent, text `#475569`. Hover: background `#F1F5F9`, text `#0F172A`.
- **Destructive:** Background `#DC2626`, text `#FFFFFF`. Hover: `#B91C1C`.

### 2. Monospace Badges & Status Chips
- **Verified Evidence:** Background `#F0FDFA`, text `#0F766E`, border 1px solid `#CCFBF1`. Displays leading 6px circular dot (`#0D9488`).
- **Conflict / Revision Pending:** Background `#FFFBEB`, text `#B45309`, border 1px solid `#FDE68A`. Leading indicator dot (`#D97706`).
- **Critical Violation:** Background `#FEF2F2`, text `#B91C1C`, border 1px solid `#FECACA`. Leading indicator dot (`#DC2626`).
- **Version & Metric Badges:** JetBrains Mono 11px, background `#F1F5F9`, text `#334155`, border 1px solid `#E2E8F0`. Padding: `2px 6px`.

### 3. Data Tables
- **Header:** Background `#F8FAFC`, height 36px, font JetBrains Mono 11px uppercase tracking `0.05em`, text `#64748B`, bottom border 1px solid `#CBD5E1`.
- **Rows:** Height 40px, background `#FFFFFF`, bottom border 1px solid `#F1F5F9`. Hover: `#F8FAFC`. Selected: `#EFF6FF` with a 2px left border in `#2563EB`.
- **Numeric & Version Cells:** Always right-aligned with `JetBrains Mono` and `font-variant-numeric: tabular-nums`.

### 4. Input Fields & Search Comboboxes
- **Base Input:** Height 32px or 36px. Background `#FFFFFF`, border 1px solid `#CBD5E1`, text `#0F172A`, placeholder `#94A3B8`. Border radius: 4px.
- **Focused State:** Border 1px solid `#2563EB`, box-shadow `0 0 0 3px rgba(37, 99, 235, 0.15)`.
- **Kbd / Command Shortcut:** JetBrains Mono 10px, background `#F1F5F9`, border 1px solid `#CBD5E1`, padding `1px 4px`, border-radius 3px.

### 5. Structured Policy Cards
- Built with a `#FFFFFF` surface, enclosed by a 1px `#E2E8F0` border.
- **Header Area:** 40px height with a subtler bottom divider (`#F1F5F9`), containing the statutory citation, breadcrumb, and a right-aligned confidence badge.
- **Body Area:** 14px Geist Regular reading text with highlighted token matches.
- **Footer Metadata Area:** Compact 28px bar displaying timestamp, parser revision ID, and export triggers.

### 6. Semantic Diff & Citation Blocks
- **Diff Container:** Split or unified view using JetBrains Mono 12px.
  - Added line: Background `rgba(13, 148, 136, 0.08)`, text `#0F766E`, left gutter bar 2px `#0D9488`.
  - Removed line: Background `rgba(220, 38, 38, 0.08)`, text `#B91C1C`, left gutter bar 2px `#DC2626`.
- **Citation Callout:** Background `#F8FAFC`, border-left 3px solid `#2563EB`, padding `8px 12px`, with direct interactive hyperlink to authoritative source text.
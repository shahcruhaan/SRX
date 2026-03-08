# SRX Landing Page — Framer Design Specification

## Design System for Institutional Financial Infrastructure

Prepared for implementation in Framer. Optimized for 1440px desktop viewport.
Audience: risk managers, portfolio strategists, financial engineers, institutional allocators.

---

## 1. Visual Atmosphere

### Design Philosophy: "The Analytical Instrument"

The SRX site should feel like looking at a well-calibrated instrument — not a startup pitch deck. Every pixel should communicate precision, restraint, and intellectual authority. The closest visual references are the typography and spacing of a Bridgewater research memo, the data density of a Bloomberg terminal's help pages, and the structural clarity of Stripe's treasury product documentation.

### Color Palette

The palette is built on four neutral anchors plus two functional status colors. No decorative accents. No gradients. No glows.

**Primary Surfaces:**

- Void (page background): `#0b0f18` — a deep navy-black, warmer than pure black, cooler than charcoal. This is the dominant surface. It reads as "control room at night" rather than "generic dark mode."
- Slate (card surfaces): `#141c2b` — one shade lighter than Void. Used for methodology boxes, product cards, and any elevated surface. The difference from the background should be perceptible but quiet.
- Graphite (borders, dividers): `#1f2b3d` — visible only when adjacent to Slate or Void. Never heavy. 1px solid only.

**Text Hierarchy:**

- Mist (primary text): `#e8edf4` — a cool near-white with a faint blue undertone. High legibility against Void. Used for headlines, metric values, and primary copy.
- Fog (secondary text): `#8d99ae` — a medium blue-grey. Used for descriptions, captions, labels, and all supporting copy. This is the workhorse color — most body text should be Fog, not Mist.
- Smoke (tertiary text): `#5a6577` — faint, receding text. Used for disclaimers, attribution lines, section dividers, and metadata.

**Functional Status Colors (used sparingly, only in risk-context elements):**

- Amber: `#c49032` — elevated risk, caution states. Never used decoratively.
- Signal Red: `#b83232` — critical risk, breach states. Appears only when something is wrong.

**Rules:**

- No color should appear without a functional reason.
- The background is never pure `#000000`. Pure black is optically harsh. Navy-black has depth.
- No surface should be lighter than `#1f2b3d` except for text.
- No white backgrounds anywhere on the page.

### Whitespace ("Air")

Whitespace is the most important design element on this page. It creates hierarchy, pacing, and the psychological sense of calm authority that institutional readers associate with credibility.

- Between major sections: 160px minimum. This creates a distinct visual "breath" between ideas.
- Between section title and first content block: 48px.
- Between paragraphs within a section: 24px.
- Between cards in a row: 24px gutter.
- Padding inside cards: 40px on all sides.
- Page margins (left/right): 120px from the 1440px viewport edge, yielding a 1200px content area.

The page should feel "roomy" — like a research paper with generous margins, not a landing page trying to pack in as much content as possible above the fold.

---

## 2. Typography Architecture

### Font Selection

**Display / Headlines: Söhne Breit (or fallback: Suisse Intl)**

Söhne Breit is wide, geometric, and authoritative. It references the mechanical precision of financial data terminals without the coldness of pure grotesques. The slight width of each letterform gives headlines a monumental quality at large sizes.

If Söhne Breit is unavailable in Framer, use Suisse Intl as a near-equivalent. Both share a neutral Swiss precision appropriate for financial infrastructure. Avoid Inter, Space Grotesk, and any font that reads "SaaS startup."

**Body / Data: Söhne (or fallback: Untitled Sans)**

Söhne (the non-Breit version) is highly legible at small sizes, renders cleanly on screen, and carries the same design DNA as the display face. Untitled Sans is an acceptable fallback — it shares the no-nonsense clarity needed for financial copy.

**Monospace (for data values, metric readouts): JetBrains Mono**

Used exclusively for numeric values in metric cards, SRS/GSRI readouts, and any context where the number itself is the focal point. JetBrains Mono has distinguishable numerals (particularly 0 vs O, 1 vs l) and tabular alignment that reads "data" rather than "code."

### Type Scale

All sizes assume a 1440px viewport.

| Element | Font | Size | Weight | Letter-Spacing | Line-Height |
|---|---|---|---|---|---|
| Hero headline | Söhne Breit | 56px | 500 (Medium) | -0.03em | 1.12 |
| Hero subheadline | Söhne | 20px | 400 (Regular) | 0em | 1.55 |
| Section title | Söhne Breit | 36px | 500 (Medium) | -0.02em | 1.20 |
| Section subtitle / H3 | Söhne | 15px | 500 (Medium) | 0.06em | 1.40 |
| Body copy | Söhne | 17px | 400 (Regular) | 0.005em | 1.65 |
| Card title | Söhne Breit | 20px | 500 (Medium) | -0.01em | 1.30 |
| Card description | Söhne | 15px | 400 (Regular) | 0.005em | 1.60 |
| Caption / label | Söhne | 12px | 500 (Medium) | 0.08em | 1.40 |
| Metric value | JetBrains Mono | 32px | 600 (SemiBold) | -0.02em | 1.10 |
| Disclaimer | Söhne | 13px | 400 (Regular) | 0.005em | 1.55 |

### Typography Rules

- Section subtitles (H3) are always UPPERCASE with wide letter-spacing (0.06em). This creates a mechanical, labeling quality — like a field header on a terminal screen. Color: Fog.
- Hero headline uses Medium weight, not Bold. Bold feels promotional. Medium feels authoritative.
- Body copy line-height is generous (1.65) to create readability and air within dense analytical text.
- Never use italic for emphasis. Use Medium weight or Mist color to create emphasis within Fog body copy.
- Metric values in JetBrains Mono should always be Mist color, never Fog. The number is the most important element.

---

## 3. Section-by-Section Layout

### Section 1: Hero

**Layout:** Full-width, vertically centered, text-only. No imagery. No background decoration.

**Structure:**

- Top: 80px of empty space below a minimal fixed navigation bar (logo left, two ghost buttons right: "Live Demo" and "Whitepaper").
- Center: Headline in Söhne Breit 56px, Mist color. Two lines, left-aligned within the 1200px content grid. Line break between "Measure Systemic Risk." and "Price Portfolio Crash Protection."
- Below headline (16px gap): Subheadline in Söhne 20px, Fog color. One line.
- Below subheadline (12px gap): Description paragraph in Söhne 17px, Smoke color. Two sentences max.
- Below description (24px gap): Proof line in Söhne 13px, Smoke color, with 0.06em letter-spacing. "Built as a working prototype with a live risk dashboard, stress-testing engine, and clearinghouse simulation." This line is the credential. It should read like a footnote, not a headline.
- Below proof line (40px gap): Two buttons side by side. "View Live Demo" as a bordered button (1px Graphite border, Fog text, no fill). "Download Whitepaper" as text-only with a subtle right arrow (→).

**Rationale:** A text-only hero communicates confidence. Companies that need flashy hero imagery are compensating. SRX leads with language and lets the precision of the copy do the work. The Bloomberg terminal has no hero image. Neither does this site.

**Height:** Natural content height plus 80px top padding and 160px bottom padding.

### Section 2: The Problem

**Layout:** Full-width narrative section. Asymmetric two-column.

**Structure:**

- Left column (35% width): Section title "The Structural Gap in Crash Protection" in Söhne Breit 36px, Mist. Pinned to the top of the section.
- Right column (55% width, 10% gap): Three paragraphs of body copy in Söhne 17px, Fog. Generous paragraph spacing (24px between paragraphs).
- Below the two-column block (64px gap): A horizontal row of four summary bullet points, each in its own cell of a 4-column grid. Each bullet uses a thin vertical line (2px wide, 40px tall, Graphite color) as a visual marker instead of a dot. Text below the line in Söhne 15px, Fog.

**Rationale:** The asymmetric layout creates visual interest without decoration. The left-pinned title acts as a "section label" — a pattern from academic papers and financial research PDFs. The bullet points as a 4-column grid are scannable at a glance.

### Section 3: The Product

**Layout:** Bento grid. Three cards in a horizontal row.

**Structure:**

- Section header: "THE SRX PLATFORM" as an uppercase label (Söhne 12px, 0.08em tracking, Smoke), followed by a one-sentence description in Söhne 17px, Fog. Centered above the cards.
- Three cards, equal width, 24px gutter:
  - Card surface: Slate (`#141c2b`) with 1px Graphite border.
  - Card padding: 40px all sides.
  - Card title: Söhne Breit 20px, Mist. Example: "Systemic Risk Monitoring"
  - Below title (8px gap): A thin horizontal rule, 40px wide, 1px, Graphite. This is a structural separator, not decoration.
  - Below rule (16px gap): Card description in Söhne 15px, Fog.
  - Card height: Natural content height, all three cards equal height (CSS flex stretch).
  - Card corner radius: 4px. Barely rounded. Institutional, not playful.

**Rationale:** Bento grid conveys modularity and system thinking — the platform has distinct components that work together. Equal-width cards communicate parity between the three pillars.

### Section 4: How It Works

**Layout:** Four-step horizontal sequence. No connecting arrows. No timeline decoration.

**Structure:**

- Section header: "FROM MEASUREMENT TO PROTECTION" as uppercase label, centered.
- Four columns, equal width, 24px gutter.
- Each step:
  - Step number: JetBrains Mono 13px, Smoke color. "01" / "02" / "03" / "04". Tabular numerals.
  - Below number (12px gap): Step title in Söhne Breit 18px, Mist. Example: "Measure Systemic Stress"
  - Below title (8px gap): Step description in Söhne 15px, Fog. One sentence.
  - No connecting lines, arrows, or decorative elements between steps. The sequential numbering and horizontal reading order are sufficient. Arrows are a crutch.

**Rationale:** The numbered grid reads like a process specification — methodical and clear. The absence of decorative connectors communicates that the platform's logic is self-evident.

### Section 5: Why It Matters

**Layout:** Full-width narrative section. Single centered column, narrow (720px max-width within the 1200px grid).

**Structure:**

- Section header: Söhne Breit 36px, Mist, centered.
- Two paragraphs of body copy, Söhne 17px, Fog, centered text alignment.
- Below paragraphs (48px gap): Four significance points in a 2×2 grid. Each point uses a thin left border (2px, Graphite) as the only visual marker. Text in Söhne 15px, Fog.

**Rationale:** Centered narrow-column text is the format of editorial authority — it's how the Economist's opinion pieces and Bridgewater's daily observations are typeset. It signals "this is worth reading slowly."

### Section 6: Demo / Whitepaper

**Layout:** Single card, full content width, Slate background.

**Structure:**

- Card surface: Slate with 1px Graphite border. 64px padding all sides.
- Left-aligned section label: "EXPLORE THE RESEARCH PROTOTYPE" in uppercase Söhne 12px, Smoke.
- Below (16px gap): Two paragraphs in Söhne 17px, Fog.
- Below text (32px gap): Two buttons, same styling as hero buttons.

**Rationale:** Enclosing this section in a card creates a visual "container" that feels like a discrete panel — like an access portal or a dossier cover page.

### Section 7: Methodology Gate

**Layout:** Centered, narrow (800px max), with a form-like structure.

**Structure:**

- Section label: "REQUEST THE SRX METHODOLOGY BRIEF" in Söhne Breit 24px, Mist, centered.
- Below (16px gap): One paragraph in Söhne 15px, Fog, centered.
- Below (24px gap): Two columns listing what the briefing covers (left) and who it's prepared for (right). Each item preceded by a small dash (—) in Smoke color.
- Below (40px gap): A single centered button, "Request Methodology Brief", bordered, slightly larger than standard buttons (48px height vs 40px). The button should feel like a controlled point of entry, not a generic CTA.

**Rationale:** This section should feel like a gated entrance to a private research library. The narrow width, centered layout, and minimal decoration create a sense of exclusivity. The button is an invitation, not a demand.

### Section 8: Footer

**Layout:** Full-width, minimal. Two-column.

**Structure:**

- Left column: "Systemic Risk Exchange (SRX)" in Söhne Breit 16px, Mist. Below: one-sentence description in Söhne 13px, Smoke. Below: "research@srx-platform.com" in Söhne 13px, Fog.
- Right column: Disclaimer text in Söhne 12px, Smoke, right-aligned.
- Top border: 1px Graphite, full width.
- Padding: 48px top, 80px bottom.

**Rationale:** The footer should be almost invisible — quiet, small, and purely functional. The disclaimer is a regulatory necessity, not a design feature.

---

## 4. Component Mapping

### Framer Component Structures

**Metric Card (reusable for SRS, GSRI, PRI readouts):**

- Container: 200px wide, auto height, Slate fill, 1px Graphite border, 4px radius, 24px padding.
- Label: Söhne 12px uppercase, Smoke, 0.06em tracking.
- Value: JetBrains Mono 32px, Mist.
- Delta/status: Söhne 13px. Color determined by context: Fog for neutral, Amber for elevated, Signal Red for critical.

**Product Card:**

- Container: Flex 1 (equal width in row), Slate fill, 1px Graphite border, 4px radius, 40px padding.
- Title: Söhne Breit 20px, Mist.
- Divider: 40px wide, 1px Graphite, 16px vertical margin.
- Description: Söhne 15px, Fog.

**Ghost Button (primary CTA style):**

- Height: 44px, padding: 0 24px.
- Background: transparent.
- Border: 1px Graphite.
- Text: Söhne 14px, 500 weight, Fog.
- Hover: Border becomes Fog, text becomes Mist. Transition: 0.2s ease-out.
- No fill transition. No elevation. Just a color shift.

**Text Link Button (secondary CTA style):**

- No border, no background.
- Text: Söhne 14px, 400 weight, Fog.
- Suffix: " →" in Smoke.
- Hover: Text shifts to Mist, arrow shifts right 4px. Transition: 0.2s ease-out.

### Systemic Risk Monitoring (analytical component feel)

When placing a GSRI/SRS visualization, frame it inside a "monitor panel":
- Outer container: Slate fill, 1px Graphite border, 4px radius.
- Inner top bar: 8px height strip with a subtle label ("GSRI — REAL-TIME" in Söhne 10px uppercase, Smoke, right-aligned within the bar). This mimics the header bar of a terminal window.
- Content area: The chart sits inside with 24px padding. No additional borders around the chart itself.

### Portfolio Stress Testing (data table feel)

Stress test results should be presented in a table-like format:
- Column headers in Söhne 12px uppercase, Smoke, 0.06em tracking.
- Values in JetBrains Mono 15px, Mist.
- Row dividers: 1px Graphite, full width.
- Alternating row backgrounds: none. Uniform Slate. The row dividers provide sufficient separation.

### Default Waterfall Simulation

The waterfall visualization should be framed like an engineering schematic:
- Each layer is a horizontal bar, full content width.
- Bar height: 48px.
- Colors: Muted fills using low-opacity versions of the status colors (Amber at 15% opacity for partially depleted, Signal Red at 15% opacity for exhausted, a quiet teal-grey at 10% opacity for intact).
- Labels left-aligned within each bar, JetBrains Mono 13px, Mist.
- Dollar amounts right-aligned within each bar, JetBrains Mono 13px, Fog.

---

## 5. Data Visualization Placement

### Screenshot Framing

All product screenshots should be treated as analytical instruments, not marketing images. They are evidence, not decoration.

**Framing method:**

- Outer container: Slate fill, 1px Graphite border, 4px radius.
- Inner padding: 12px (creates a "screen bezel" effect).
- Screenshot: Actual dashboard capture at 2x resolution, rendered at display size.
- No drop shadows. No perspective transforms. No tilted angles. No device mockups.
- A 1px Graphite inner border (inset) around the screenshot itself creates the "monitor" effect.
- Optional: A small label below the screenshot in Söhne 11px, Smoke — "SRX Dashboard — GSRI Historical View" — functioning as a figure caption.

### Placement Map

| Screenshot | Section | Position | Size |
|---|---|---|---|
| GSRI time series chart | Section 1 (Hero) or Section 3 (Product) | Below the product cards, full content width | 1200 × 600px |
| SRS gauge + risk score readout | Section 3 (Product), first card | Inset within the Systemic Risk Monitoring card | Card width, ~200px height |
| PRI radar chart | Section 3 (Product), second card | Inset within the Portfolio Stress Testing card | Card width, ~200px height |
| Waterfall depletion chart | Section 4 (How It Works) or standalone between sections | Full content width, standalone panel | 1200 × 400px |
| Correlation heatmap | Optional, between Section 3 and Section 4 | Centered, 800px wide | 800 × 500px |

### Sizing Rules

- Never stretch a screenshot. Capture at the exact resolution needed.
- Dashboard screenshots should use the dark theme of the SRX dashboard — visual consistency between the landing page and the product itself.
- If the screenshot has internal padding (Streamlit's native margins), crop it to the content area.

---

## 6. Micro-Interactions and Motion

### Motion Philosophy: "Quiet Confidence"

Motion on this site should feel like a precision mechanism settling into place — not bouncing, springing, or drawing attention to itself. Every animation serves one purpose: to smooth the transition between states so the interface feels responsive rather than static.

### Scroll Reveal

- Elements fade in from 0% to 100% opacity as they enter the viewport.
- Translation: 12px upward (start 12px below final position, settle to 0).
- Duration: 0.4s.
- Easing: `cubic-bezier(0.25, 0.1, 0.25, 1)` (a restrained ease-out).
- Stagger: If multiple elements enter simultaneously (e.g., three product cards), stagger their reveal by 80ms each (card 1 at 0ms, card 2 at 80ms, card 3 at 160ms).
- No scroll reveal on the hero section. It should be fully visible on page load with no animation.

### Hover States

- Buttons: Border and text color shift from Graphite/Fog to Fog/Mist. Duration: 0.2s ease-out. No elevation, no scale, no shadow.
- Cards: Border color shifts from Graphite to a slightly lighter `#2a3a52`. Duration: 0.2s ease-out. No elevation. The card does not "lift." It simply becomes slightly more defined.
- Links: Underline fades in (from transparent to Smoke). Duration: 0.15s.

### What to Avoid

- No `transform: scale()` on hover. Scaling is playful. This is not playful.
- No box-shadow on hover. Shadows imply depth, which implies physicality. This interface is flat and precise.
- No spring/bounce easing (`cubic-bezier` overshoots). Overshoot is whimsical. This is not whimsical.
- No parallax scrolling. Parallax is a consumer pattern.
- No auto-playing animations or looping effects. Nothing on this page should move unless the user caused it to move.

---

## 7. Methodology Gate Design

### Layout: Centered Monolith

The Methodology Gate should feel like approaching a secured entrance — a single, centered, narrow column that narrows the reader's focus.

- Max width: 800px, centered within the 1200px grid.
- Background: Slate card, 1px Graphite border, 4px radius, 64px padding.
- Interior structure:
  - Section label: "REQUEST THE SRX METHODOLOGY BRIEF" — Söhne Breit 24px, Mist, centered.
  - Below (16px): Invitation paragraph — Söhne 15px, Fog, centered.
  - Below (32px): Two columns (360px each, 80px gap):
    - Left: "Briefing Covers" — list items with em-dash prefix.
    - Right: "Prepared For" — list items with em-dash prefix.
    - List text: Söhne 14px, Fog. Em-dash in Smoke.
  - Below (40px): Single centered button, 48px height, wider than standard (200px).

### Button Design

The CTA button here should be the most prominent button on the entire page — but prominent through size and isolation, not color.

- Height: 48px (vs 44px standard).
- Width: 200px minimum.
- Border: 1px, slightly lighter than standard Graphite — use `#2a3a52`.
- Text: Söhne 14px, 500 weight, Mist (brighter than standard Fog button text).
- Hover: Border becomes Mist, background fills with a 3% opacity white (`rgba(255,255,255,0.03)`).

The button should feel like it is waiting for you. It does not beg. It is simply available, and clearly the next action.

---

## 8. Grid System and Spacing

### Grid Architecture

| Property | Value | Notes |
|---|---|---|
| Viewport | 1440px | Primary design target |
| Content max-width | 1200px | Centered within viewport |
| Page margins (each side) | 120px | (1440 - 1200) / 2 |
| Column grid | 12 columns | Standard institutional grid |
| Column width | 76px | (1200 - 11×24) / 12 |
| Gutter | 24px | Between all columns |
| Narrow content | 720px | 8 columns. Used for Section 5 (Why It Matters) centered text. |
| Medium content | 800px | Used for Methodology Gate. |

### Vertical Rhythm

All vertical spacing is based on an 8px unit.

| Spacing Context | Size | 8px Multiple |
|---|---|---|
| Between major sections | 160px | 20 units |
| Section title to first content | 48px | 6 units |
| Between paragraphs | 24px | 3 units |
| Between cards in a row | 24px | 3 units (horizontal gutter) |
| Card internal padding | 40px | 5 units |
| Button height | 44px | 5.5 units (exception) |
| Methodology Gate button height | 48px | 6 units |
| Footer top padding | 48px | 6 units |
| Footer bottom padding | 80px | 10 units |
| Hero top padding | 80px | 10 units |
| Hero bottom padding | 160px | 20 units |

### Section Height Guidelines

Sections should not have fixed heights. All heights are content-driven plus padding. The 160px inter-section spacing creates the visual breathing room.

Exception: The hero section should occupy a minimum of 80vh (80% of the viewport height) to create the sense that the page begins with a single, focused statement.

### Responsive Notes (secondary priority)

At viewports below 1024px:
- Content max-width collapses to 90% of viewport.
- 3-column card grids stack to single column.
- 4-column "How It Works" stacks to 2×2.
- Asymmetric two-column sections (Problem) stack to single column.
- Hero headline drops to 40px.
- Section spacing reduces to 120px.

No mobile-specific redesign is required. The content should reflow gracefully but the design target remains 1440px desktop.

---

## Implementation Notes for Framer

### Font Loading

If Söhne/Söhne Breit are not available in Framer's font library, upload them as custom fonts or substitute with:
- Display: Suisse Intl (available via Framer's Google Fonts integration or as custom upload)
- Body: Untitled Sans or, as a widely available fallback, DM Sans at the specified weights
- Monospace: JetBrains Mono (available on Google Fonts)

### Color Variables

Define all colors as Framer design tokens / CSS variables so the entire palette can be adjusted from one location:

- `--void`: #0b0f18
- `--slate`: #141c2b
- `--graphite`: #1f2b3d
- `--mist`: #e8edf4
- `--fog`: #8d99ae
- `--smoke`: #5a6577
- `--amber`: #c49032
- `--signal-red`: #b83232

### Framer-Specific Patterns

- Use Framer's "Stack" component for all vertical and horizontal layouts. Set gap values explicitly to match the spacing spec.
- Use "Frame" with fill and border properties for cards. Do not use effects (shadows, blurs).
- Set all text components to "Auto" width within their parent Stack to enable responsive reflow.
- Use Framer's "Scroll" trigger for reveal animations. Set transform from `translateY(12px), opacity(0)` to `translateY(0), opacity(1)` with the specified easing and duration.
- For the navigation bar, use Framer's "Fixed" positioning with a `backdrop-filter: blur(8px)` and a semi-transparent Void background (`rgba(11, 15, 24, 0.85)`) for a subtle frosted effect on scroll.

---

*End of design specification.*

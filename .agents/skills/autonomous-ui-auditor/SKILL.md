---
name: autonomous-ui-auditor
description: Autonomous browser navigation and UI audit skill. Enables the agent to navigate local and remote web applications using browser_subagent, inspect DOM elements, verify visual layouts, check formatting/rendering, and validate UI improvements without requiring the user to take or upload screenshots.
---

# Autonomous UI Auditor Skill

This skill enables Antigravity to autonomously test, navigate, inspect, and verify web applications (Streamlit, React, Next.js, HTML/CSS) directly via the browser subagent without requiring the user to take or upload manual screenshots.

## When to Use
- Validating UI layout, responsive styling, and visual rendering.
- Checking for HTML/Markdown leaks (e.g. unescaped `<pre><code>` blocks, raw CSS, broken tags).
- Verifying dynamic user interactions (button clicks, tab switches, dropdown selects, sliders).
- Inspecting charts, KPI cards, tables, badges, and alerts after code changes.
- Automated end-to-end visual regression verification.

## Core Autonomous Workflow

```
1. Healthcheck Port  ──► 2. Launch browser_subagent ──► 3. Inspect DOM & Layout
         │                                                        │
         ▼                                                        ▼
6. Re-test in Browser ◄── 5. Apply Code Edits         ◄── 4. Analyze Findings
```

### Step 1: Verify Server Status
Before launching the subagent, verify the local dev server is responding:
```python
import urllib.request
res = urllib.request.urlopen("http://localhost:8501")
assert res.status == 200
```

### Step 2: Formulate Detailed Task for `browser_subagent`
Provide clear, actionable instructions:
- **Exact URL:** `http://localhost:8501/Monthly_SIP_and_Sell_Radar` (or navigate via sidebar).
- **Wait Condition:** Wait for Streamlit connection state (`data-testid="stAppViewContainer"` or specific headers).
- **Target Elements:** List specific headings, KPI cards, buttons, tabs, tables, or charts to inspect.
- **Interaction Sequence:** Click specific tabs (e.g., Step 1, Step 2), toggle presets, or trigger recalculations.
- **Reporting Requirement:** Require the subagent to report the exact text, computed values, visibility, and any rendering anomalies.

### Step 3: Common UI Flaws to Auto-Detect
1. **Markdown / HTML Code Block Leaks:**
   - Raw HTML or comments (`<!-- ... -->`) causing Streamlit CommonMark to render as `<pre><code>`.
   - Fix: Use custom sanitizers like `render_clean_html()`.
2. **Chart Value Overflows / Overlaps:**
   - Giant 11-digit numbers on Plotly charts overlapping lines.
   - Fix: Format in Indian numbering (`₹58.5 L`, `₹3.06 Cr`, `₹33.22 Cr`) with full rupee tooltips.
3. **Card / Metric Clutter:**
   - Multi-column layouts where text wraps awkwardly.
4. **Sequence & Flow Consistency:**
   - Steps out of order (e.g., Step 3 appearing before Step 1).

### Step 4: Autonomous Iteration Loop
1. Run `browser_subagent` to capture the current state.
2. Read subagent report & artifact video/recording.
3. Apply code fixes to target Python / CSS / JS files.
4. Re-run `browser_subagent` to confirm the fix is 100% verified.
5. Report verified status to user with zero screenshot requests.

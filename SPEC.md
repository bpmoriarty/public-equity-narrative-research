# SPEC.md

## 1. Document scope

Five fiscal years. Per year:

| Form | Why it's in scope | Target sections |
|---|---|---|
| **10-K** | Management's own account of strategy and risk | Item 1 (Business), Item 1A (Risk Factors), Item 7 (MD&A) |
| **DEF 14A** | What the board actually incentivizes; board composition | Compensation Discussion & Analysis, incentive metric tables, director bios and tenure, shareholder proposals and vote results |
| **Shareholder / annual letter** | Leadership voice and stated priorities, unfiltered by disclosure convention | Full text (usually short) |
| **8-K** | Discrete material events between annual filings | **Filtered** — see below |

### 8-K filtering

Do not process every 8-K; a large filer produces dozens a year, mostly
routine. Include only these items:

- **1.01 / 1.02** — material agreements entered or terminated
- **2.01** — completion of acquisition or disposition
- **2.05** — costs associated with exit or disposal activities (restructuring)
- **5.02** — director and officer departures, appointments, elections
- **5.07** — submission of matters to a shareholder vote
- **7.01 / 8.01** — regulation FD and other events, **only** where the exhibit
  is a strategic announcement rather than a routine press release

Exclude routine earnings releases (2.02) from processing, but log their dates —
the cadence itself is timeline context.

### Out of scope

Earnings call transcripts are not in EDGAR and are **not** part of the core
build. If a transcript source is available, treat it as an optional later
enhancement; do not block the pipeline on it.

## 2. Extraction targets

Beyond raw section text, extract these specific signals:

**Strategic**
- Stated strategic priorities per year, in management's own phrasing
- Priorities that appear, disappear, or change emphasis between years — the
  deltas matter more than any single year's list
- Segment or business line structure, and any re-segmentation (a re-segmentation
  is almost always a strategic signal)
- Stated headcount and any material change

**Governance and leadership**
- Executive team composition and every change, with date and stated reason
- Board composition, tenure, committee structure, and turnover
- Incentive plan metrics — what specifically pays out, at what weighting, and
  whether the metrics change year over year
- Say-on-pay results and any shareholder proposals with vote outcomes

**Risk**
- Risk factors added, removed, or materially reworded year over year. New and
  deleted risk factors are high-signal; unchanged boilerplate is noise. Diff
  rather than summarizing each year independently.

**Events**
- Acquisitions, divestitures, restructurings, impairments, major financings
- Leadership transitions
- Guidance changes or withdrawals where disclosed

## 3. Year ledger schema

One JSON record per fiscal year in `data/ledger/`. Suggested shape — adjust if
the filings demand it, but keep every field sourced:

```json
{
  "fiscal_year": 2023,
  "filings": [{"form": "10-K", "accession": "...", "filed": "2024-02-15"}],
  "strategic_priorities": [{"text": "...", "source": "10-K Item 1", "accession": "..."}],
  "segments": [{"name": "...", "note": "renamed from X", "source": "..."}],
  "headcount": {"value": 0, "source": "..."},
  "leadership": [{"name": "...", "role": "...", "change": "appointed|departed", "date": "...", "stated_reason": "...", "source": "..."}],
  "board": {"size": 0, "changes": [], "committees": [], "source": "..."},
  "incentive_metrics": [{"metric": "...", "weight": "...", "source": "..."}],
  "risk_deltas": {"added": [], "removed": [], "reworded": [], "source": "..."},
  "events": [{"type": "acquisition", "description": "...", "date": "...", "source": "..."}],
  "notable_language": [{"quote_or_paraphrase": "...", "why_notable": "...", "source": "..."}]
}
```

Everything downstream derives from this layer. Do not generate outputs directly
from raw sections.

## 4. Outputs

All three go in `output/` as Markdown.

### 4a. `narrative-brief.md`

Prose. Roughly 1,500–2,500 words. Read once and understand the company's arc.

Structure:
- Where the company stood five years ago — position, strategy, leadership
- The arc: how strategy, structure, and leadership changed across the window,
  and what appears to have driven each shift
- Where it stands now: current strategic position, stated priorities, and the
  risks management itself emphasizes
- Open questions the filings raise but don't answer

Written as analysis, not summary. Say what changed and what it suggests, not
"in 2022 the company filed a 10-K stating..."

### 4b. `timeline.md`

Reference document, not prose. Chronological table of concrete, dated events:
leadership changes, M&A, restructurings, segment changes, incentive plan
changes, major financings. Every row carries a source. Skimmable in two
minutes.

### 4c. `discussion-points.md`

The analytical output. Three sections:

1. **Observations** — patterns visible across the five years that aren't
   visible in any single filing. Emphasis shifts, gaps between stated priority
   and incentive structure, recurring unresolved themes, language that changed
   meaningfully.
2. **Open questions** — specific, substantive questions the filings raise. Not
   generic; each should be answerable only by someone inside the company, and
   should demonstrate that the filings were actually read closely.
3. **What management appears to prioritize** — inferred from incentive plan
   metrics, repeated language across letters, and capital allocation, with the
   evidence for each inference stated. Where stated priorities and paid-for
   priorities diverge, flag it explicitly — that divergence is the single most
   useful thing this pipeline can surface.

## 5. Milestones

Check in before proceeding past each:

1. Filing inventory and gap analysis
2. Fetch and cache complete
3. One extracted section reviewed end-to-end, then full extraction
4. Year ledger built
5. Three outputs generated

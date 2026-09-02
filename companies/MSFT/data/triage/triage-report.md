# 8-K triage log — conditional items 7.01 / 8.01

MSFT (MICROSOFT CORP), CIK 0000789019. When this last ran is in `data/_meta/run-log.json` — not here, so re-running reproduces this file byte for byte.

Deterministic: no model calls, so the same inputs always give the same decisions and every one can be checked by hand. `config/forms.toml` requires this log — "Log every triage decision; a silent drop here loses real events."

**A `date_only` decision requires positive evidence of a routine filing AND the absence of every material signal, including passing mentions.** Anything unrecognised is read. The full drop list is printed below so it can be audited by eye, which is the actual safety net here — the classifier is only the first pass.

## Summary

- filings triaged: **25**
- read: **25**
- date_only: **0**
- content to read, after stripping boilerplate: **301,302** chars

- documents over the 120,000-char cap and therefore **not read**: **1**
  - 2024-12-03 0000950170-24-132722 EX-99.1 — 198,090 chars

## By fiscal year

| FY | triaged | read | date_only | content chars |
|---|---|---|---|---|
| FY2020 | 6 | 6 | 0 | 87,597 |
| FY2021 | 7 | 7 | 0 | 95,347 |
| FY2022 | 3 | 3 | 0 | 22,730 |
| FY2023 | 1 | 1 | 0 | 6,162 |
| FY2024 | 6 | 6 | 0 | 67,267 |
| FY2025 | 2 | 2 | 0 | 22,199 |

## Where the content sits, by year

The Reg FD investor Q&A moved from the 8-K body to an EX-99.1 exhibit inside the window. A bodies-only reader would silently return nothing for the later years.

| FY | content in body | content in exhibit |
|---|---|---|
| FY2020 | 2 | 6 |
| FY2021 | 1 | 6 |
| FY2022 | 0 | 1 |
| FY2023 | 1 | 1 |
| FY2024 | 6 | 5 |
| FY2025 | 1 | 2 |

## Signal counts

`strong` = matched inside the first 1,200 characters, where a press release states its subject. `mention` = matched later, which on this corpus usually means management discussing something in a Q&A answer rather than announcing it. Only strong material matches drive routing.

| signal | strong | mention |
|---|---|---|
| deal | 2 | 4 |
| leadership | 0 | 1 |
| presentation | 0 | 3 |

## date_only — the full drop list, for audit

_Nothing was dropped._

## read — every kept filing

| filed | FY | items | chars | routes to | reason |
|---|---|---|---|---|---|
| 2020-02-26 | FY2020 | 7.01, 9.01 | 7,672 | events | no signal matched at all — unrecognised filings are read, never dropped, because a wrong drop is undetectable downstream |
| 2020-03-31 | FY2020 | 7.01, 9.01 | 9,238 | events | no signal matched at all — unrecognised filings are read, never dropped, because a wrong drop is undetectable downstream |
| 2020-04-30 | FY2020 | 8.01, 9.01 | 21,635 | events | no signal matched at all — unrecognised filings are read, never dropped, because a wrong drop is undetectable downstream |
| 2020-05-14 | FY2020 | 8.01, 9.01 | 26,495 | events | no signal matched at all — unrecognised filings are read, never dropped, because a wrong drop is undetectable downstream |
| 2020-06-01 | FY2020 | 8.01, 9.01 | 13,347 | events | no signal matched at all — unrecognised filings are read, never dropped, because a wrong drop is undetectable downstream |
| 2020-06-26 | FY2020 | 7.01, 9.01 | 9,210 | events | no signal matched at all — unrecognised filings are read, never dropped, because a wrong drop is undetectable downstream |
| 2020-08-03 | FY2021 | 7.01, 9.01 | 3,592 | events | material signal (deal) matched outside the headline window, so it is a mention rather than an announcement — read, because only a reader can tell those apart |
| 2020-09-21 | FY2021 | 7.01, 9.01 | 10,641 | events | strong material signal: deal |
| 2021-02-16 | FY2021 | 8.01, 9.01 | 22,923 | events | no signal matched at all — unrecognised filings are read, never dropped, because a wrong drop is undetectable downstream |
| 2021-03-02 | FY2021 | 8.01, 9.01 | 29,363 | events | no signal matched at all — unrecognised filings are read, never dropped, because a wrong drop is undetectable downstream |
| 2021-03-17 | FY2021 | 8.01, 9.01 | 13,935 | events | no signal matched at all — unrecognised filings are read, never dropped, because a wrong drop is undetectable downstream |
| 2021-04-12 | FY2021 | 7.01, 9.01 | 14,893 | investor_qa | narrative content: presentation |
| 2021-06-17 | FY2021 | 8.01 | 0 | events | no signal matched at all — unrecognised filings are read, never dropped, because a wrong drop is undetectable downstream |
| 2021-07-08 | FY2022 | 8.01, 9.01 | 2,745 | events | no signal matched at all — unrecognised filings are read, never dropped, because a wrong drop is undetectable downstream |
| 2022-01-18 | FY2022 | 7.01, 9.01 | 16,174 | events, investor_qa | material signal (deal) in a document that also carries narrative content (presentation) |
| 2022-06-02 | FY2022 | 7.01, 9.01 | 3,811 | events | no signal matched at all — unrecognised filings are read, never dropped, because a wrong drop is undetectable downstream |
| 2023-01-18 | FY2023 | 7.01, 9.01 | 6,162 | events | material signal (deal) matched outside the headline window, so it is a mention rather than an announcement — read, because only a reader can tell those apart |
| 2023-10-11 | FY2024 | 8.01, 9.01 | 5,609 | events | no signal matched at all — unrecognised filings are read, never dropped, because a wrong drop is undetectable downstream |
| 2023-10-16 | FY2024 | 8.01, 9.01 | 20,059 | events | no signal matched at all — unrecognised filings are read, never dropped, because a wrong drop is undetectable downstream |
| 2023-10-30 | FY2024 | 8.01, 9.01 | 16,391 | events | no signal matched at all — unrecognised filings are read, never dropped, because a wrong drop is undetectable downstream |
| 2023-11-06 | FY2024 | 8.01, 9.01 | 12,989 | events | material signal (leadership) matched outside the headline window, so it is a mention rather than an announcement — read, because only a reader can tell those apart |
| 2024-01-19 | FY2024 | 1.05, 7.01, 9.01 | 5,896 | events | no signal matched at all — unrecognised filings are read, never dropped, because a wrong drop is undetectable downstream |
| 2024-03-08 | FY2024 | 1.05, 7.01, 9.01 | 6,323 | events | no signal matched at all — unrecognised filings are read, never dropped, because a wrong drop is undetectable downstream |
| 2024-08-21 | FY2025 | 7.01, 9.01 | 18,300 | investor_qa | narrative content: presentation |
| 2024-12-03 | FY2025 | 8.01, 9.01 | 3,899 | events | material signal (deal) matched outside the headline window, so it is a mention rather than an announcement — read, because only a reader can tell those apart |
# 8-K triage log — conditional items 7.01 / 8.01

Generated 2026-08-24T15:14:24Z. MORN (Morningstar, Inc.), CIK 0001289419.

Deterministic: no model calls, so the same inputs always give the same decisions and every one can be checked by hand. `config/forms.toml` requires this log — "Log every triage decision; a silent drop here loses real events."

**A `date_only` decision requires positive evidence of a routine filing AND the absence of every material signal, including passing mentions.** Anything unrecognised is read. The full drop list is printed below so it can be audited by eye, which is the actual safety net here — the classifier is only the first pass.

## Summary

- filings triaged: **75**
- read: **60**
- date_only: **15**
- content to read, after stripping boilerplate: **1,261,770** chars

## By fiscal year

| FY | triaged | read | date_only | content chars |
|---|---|---|---|---|
| FY2021 | 13 | 9 | 4 | 149,611 |
| FY2022 | 15 | 14 | 1 | 230,221 |
| FY2023 | 19 | 15 | 4 | 335,366 |
| FY2024 | 12 | 10 | 2 | 239,477 |
| FY2025 | 16 | 12 | 4 | 307,095 |

## Where the content sits, by year

The Reg FD investor Q&A moved from the 8-K body to an EX-99.1 exhibit inside the window. A bodies-only reader would silently return nothing for the later years.

| FY | content in body | content in exhibit |
|---|---|---|
| FY2021 | 8 | 2 |
| FY2022 | 12 | 3 |
| FY2023 | 14 | 0 |
| FY2024 | 3 | 7 |
| FY2025 | 0 | 12 |

## Signal counts

`strong` = matched inside the first 1,200 characters, where a press release states its subject. `mention` = matched later, which on this corpus usually means management discussing something in a Q&A answer rather than announcing it. Only strong material matches drive routing.

| signal | strong | mention |
|---|---|---|
| capital_allocation | 1 | 1 |
| deal | 7 | 17 |
| dividend | 16 | 16 |
| investor_qa | 18 | 53 |
| leadership | 0 | 2 |
| presentation | 1 | 4 |

## date_only — the full drop list, for audit

| filed | accession | items | reason |
|---|---|---|---|
| 2021-02-24 | 0001104659-21-027572 | 8.01, 9.01 | routine filing (dividend) and no material signal anywhere in the document, not even a passing mention |
| 2021-05-17 | 0001104659-21-067825 | 8.01, 9.01 | routine filing (dividend) and no material signal anywhere in the document, not even a passing mention |
| 2021-10-12 | 0001104659-21-125162 | 8.01, 9.01 | routine filing (dividend) and no material signal anywhere in the document, not even a passing mention |
| 2021-12-06 | 0001104659-21-146663 | 8.01, 9.01 | routine filing (dividend) and no material signal anywhere in the document, not even a passing mention |
| 2022-03-02 | 0001104659-22-029183 | 8.01, 9.01 | routine filing (dividend) and no material signal anywhere in the document, not even a passing mention |
| 2023-03-21 | 0001104659-23-035071 | 8.01, 9.01 | routine filing (dividend) and no material signal anywhere in the document, not even a passing mention |
| 2023-06-16 | 0001104659-23-072246 | 8.01, 9.01 | routine filing (dividend) and no material signal anywhere in the document, not even a passing mention |
| 2023-09-15 | 0001104659-23-101202 | 8.01, 9.01 | routine filing (dividend) and no material signal anywhere in the document, not even a passing mention |
| 2023-12-01 | 0001104659-23-122850 | 8.01, 9.01 | routine filing (dividend) and no material signal anywhere in the document, not even a passing mention |
| 2024-06-18 | 0001289419-24-000044 | 8.01, 9.01 | routine filing (dividend) and no material signal anywhere in the document, not even a passing mention |
| 2024-09-18 | 0001289419-24-000097 | 8.01, 9.01 | routine filing (dividend) and no material signal anywhere in the document, not even a passing mention |
| 2025-03-14 | 0001289419-25-000058 | 8.01, 9.01 | routine filing (dividend) and no material signal anywhere in the document, not even a passing mention |
| 2025-06-20 | 0001289419-25-000132 | 8.01, 9.01 | routine filing (dividend) and no material signal anywhere in the document, not even a passing mention |
| 2025-09-19 | 0001289419-25-000154 | 8.01, 9.01 | routine filing (dividend) and no material signal anywhere in the document, not even a passing mention |
| 2025-12-05 | 0001289419-25-000176 | 8.01, 9.01 | routine filing (dividend) and no material signal anywhere in the document, not even a passing mention |

## read — every kept filing

| filed | FY | items | chars | routes to | reason |
|---|---|---|---|---|---|
| 2021-03-12 | FY2021 | 7.01 | 17,321 | investor_qa | narrative content: investor_qa |
| 2021-03-19 | FY2021 | 7.01, 9.01 | 14,029 | investor_qa | narrative content: presentation |
| 2021-04-16 | FY2021 | 7.01 | 13,457 | investor_qa | narrative content: investor_qa |
| 2021-06-11 | FY2021 | 7.01 | 45,339 | investor_qa | narrative content: investor_qa |
| 2021-07-09 | FY2021 | 7.01 | 9,555 | investor_qa | narrative content: investor_qa |
| 2021-08-13 | FY2021 | 7.01 | 3,942 | investor_qa | narrative content: investor_qa |
| 2021-09-17 | FY2021 | 7.01 | 21,964 | investor_qa | narrative content: investor_qa |
| 2021-11-12 | FY2021 | 7.01 | 12,708 | investor_qa | narrative content: investor_qa |
| 2021-12-22 | FY2021 | 7.01, 9.01 | 11,296 | events | strong material signal: deal |
| 2022-02-18 | FY2022 | 7.01 | 3,381 | investor_qa | narrative content: investor_qa |
| 2022-03-18 | FY2022 | 7.01 | 14,387 | investor_qa | narrative content: investor_qa |
| 2022-04-22 | FY2022 | 7.01 | 27,215 | investor_qa | narrative content: investor_qa |
| 2022-05-27 | FY2022 | 7.01 | 19,430 | investor_qa | narrative content: investor_qa |
| 2022-06-01 | FY2022 | 7.01, 9.01 | 7,908 | events | strong material signal: deal |
| 2022-06-17 | FY2022 | 7.01 | 7,505 | investor_qa | narrative content: investor_qa |
| 2022-07-01 | FY2022 | 7.01, 9.01 | 11,216 | events | strong material signal: deal |
| 2022-07-22 | FY2022 | 7.01 | 26,609 | investor_qa | narrative content: investor_qa, presentation |
| 2022-08-26 | FY2022 | 7.01 | 16,797 | investor_qa | narrative content: investor_qa |
| 2022-09-23 | FY2022 | 7.01 | 47,819 | investor_qa | narrative content: investor_qa |
| 2022-10-21 | FY2022 | 7.01 | 11,198 | investor_qa | narrative content: investor_qa |
| 2022-11-18 | FY2022 | 7.01 | 9,587 | investor_qa | narrative content: investor_qa |
| 2022-12-09 | FY2022 | 8.01, 9.01 | 7,650 | events | strong material signal: capital_allocation |
| 2022-12-22 | FY2022 | 7.01 | 19,519 | investor_qa | narrative content: investor_qa |
| 2023-01-24 | FY2023 | 7.01 | 7,344 | investor_qa | narrative content: investor_qa |
| 2023-01-31 | FY2023 | 8.01 | 2,433 | events | material signal (deal) matched outside the headline window, so it is a mention rather than an announcement — read, because only a reader can tell those apart |
| 2023-02-24 | FY2023 | 7.01 | 1,597 | investor_qa | narrative content: investor_qa |
| 2023-03-23 | FY2023 | 7.01 | 32,721 | investor_qa | narrative content: investor_qa, presentation |
| 2023-03-29 | FY2023 | 7.01 | 25,975 | investor_qa | narrative content: investor_qa |
| 2023-04-05 | FY2023 | 7.01 | 26,993 | investor_qa | narrative content: investor_qa |
| 2023-04-14 | FY2023 | 7.01 | 41,958 | investor_qa | narrative content: investor_qa |
| 2023-05-11 | FY2023 | 7.01 | 28,869 | investor_qa | narrative content: investor_qa |
| 2023-06-12 | FY2023 | 7.01 | 7,434 | investor_qa | narrative content: investor_qa |
| 2023-07-06 | FY2023 | 7.01 | 39,696 | investor_qa | narrative content: investor_qa |
| 2023-08-21 | FY2023 | 7.01 | 19,478 | investor_qa | narrative content: investor_qa |
| 2023-09-08 | FY2023 | 7.01 | 18,308 | investor_qa | narrative content: investor_qa |
| 2023-10-02 | FY2023 | 7.01 | 27,487 | investor_qa | narrative content: investor_qa |
| 2023-10-23 | FY2023 | 7.01 | 24,522 | investor_qa | narrative content: investor_qa |
| 2023-12-19 | FY2023 | 7.01 | 30,551 | investor_qa | narrative content: investor_qa |
| 2024-02-05 | FY2024 | 7.01 | 24,571 | investor_qa | narrative content: investor_qa |
| 2024-03-22 | FY2024 | 7.01 | 26,762 | investor_qa | narrative content: investor_qa |
| 2024-05-09 | FY2024 | 7.01 | 31,802 | investor_qa | narrative content: investor_qa |
| 2024-06-14 | FY2024 | 7.01, 9.01 | 8,065 | investor_qa | narrative content: investor_qa |
| 2024-06-20 | FY2024 | 7.01, 9.01 | 15,061 | events, investor_qa | material signal (deal) in a document that also carries narrative content (investor_qa) |
| 2024-07-18 | FY2024 | 7.01, 9.01 | 31,323 | investor_qa | narrative content: investor_qa, presentation |
| 2024-08-26 | FY2024 | 7.01, 9.01 | 10,673 | events, investor_qa | material signal (deal) in a document that also carries narrative content (investor_qa) |
| 2024-10-01 | FY2024 | 7.01, 9.01 | 45,797 | investor_qa | narrative content: investor_qa |
| 2024-11-12 | FY2024 | 7.01, 9.01 | 9,018 | investor_qa | narrative content: investor_qa |
| 2024-12-13 | FY2024 | 7.01, 9.01 | 36,405 | investor_qa | narrative content: investor_qa |
| 2025-01-31 | FY2025 | 7.01, 9.01 | 12,486 | investor_qa | narrative content: investor_qa |
| 2025-03-25 | FY2025 | 7.01, 9.01 | 16,230 | investor_qa | narrative content: investor_qa |
| 2025-04-29 | FY2025 | 7.01, 9.01 | 28,267 | investor_qa | narrative content: investor_qa |
| 2025-05-07 | FY2025 | 7.01, 9.01 | 48,088 | investor_qa | narrative content: investor_qa |
| 2025-06-27 | FY2025 | 7.01, 9.01 | 31,609 | investor_qa | narrative content: investor_qa |
| 2025-08-05 | FY2025 | 7.01, 9.01 | 11,576 | investor_qa | narrative content: investor_qa |
| 2025-08-29 | FY2025 | 7.01, 9.01 | 30,912 | investor_qa | narrative content: investor_qa |
| 2025-09-23 | FY2025 | 7.01, 9.01 | 11,442 | events | strong material signal: deal |
| 2025-09-26 | FY2025 | 7.01, 9.01 | 39,616 | investor_qa | narrative content: investor_qa |
| 2025-11-05 | FY2025 | 7.01, 9.01 | 45,136 | investor_qa | narrative content: investor_qa |
| 2025-11-25 | FY2025 | 7.01, 9.01 | 28,441 | investor_qa | narrative content: investor_qa |
| 2025-12-23 | FY2025 | 7.01, 9.01 | 3,292 | investor_qa | narrative content: investor_qa |
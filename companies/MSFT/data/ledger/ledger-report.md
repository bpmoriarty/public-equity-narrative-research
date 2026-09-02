# Year ledger

MSFT (MICROSOFT CORP), CIK 0000789019. When this last ran is in `data/_meta/run-log.json` — not here, so re-running reproduces this file byte for byte.

Every fact carries its source filing, an exact quote from that filing, and a confidence marker. `low` means the source section's boundaries are unverified, or the quote could not be found verbatim — see `confidence_reason` on the fact. **Any claim in the outputs resting on a `low` fact must say so, or be dropped.**

Every fact and risk delta also carries a stable `id` — e.g. `SP-FY2020-68ae8f40` — hashed from its claim, its evidence and its source, so an output can cite one fact rather than a whole filing. Confidence and the verification result are deliberately NOT in the hash: a judgment about a fact is not the fact, so re-verifying it later must not renumber it. 809 ids this build, checked unique.

## Coverage

| Field | FY2020 | FY2021 | FY2022 | FY2023 | FY2024 | FY2025 |
|---|---|---|---|---|---|---|
| strategic_priorities | 16 | 16 | 15 | 30 | 27 | 27 |
| segments | 3 | 3 | 6 | 6 | 3 | 6 |
| headcount | 1 | 1 | 1 | 1 | 1 | 1 |
| leadership | 6 | 16 | 4 | 12 | 2 | 1 |
| board | 12 (12 low) | 12 (12 low) | 12 (12 low) | 12 (12 low) | 12 (12 low) | 12 (12 low) |
| incentive_metrics | 21 | 15 | 18 | 12 | 15 | 15 |
| vote_results | 15 | 20 | 20 | 24 | 20 | 21 |
| events | 9 | 11 | 15 | 9 | 12 | 11 |
| notable_language | 23 (1 low) | 26 | 22 | 33 | 32 (1 low) | 35 |
| investor_qa | 0 | 14 | 13 | 0 | 0 | 11 |
| risk_deltas (added/removed/reworded) | baseline | +1/-0/~2 | +0/-1/~1 | +1/-0/~2 | +0/-0/~3 | +0/-0/~1 |
| segments basis | reportable | reportable | reportable | reportable | reportable | reportable |

## Document window

The **fiscal window** is FY2020–FY2025 (`2019-07-01` .. `2025-06-30` in calendar time). That bounds the fiscal years in scope, not the documents.

The **document window** — the filing dates of the documents these facts are actually drawn from — is **`2019-09-19` .. `2025-12-08`**, across 32 filings. It extends past the fiscal window end by construction: a 10-K, a proxy and an annual-meeting vote all report on a year after that year has closed.

1 of those filings also belongs to a fiscal year outside the window, and is used deliberately — an annual-meeting vote held in May of year N decides on year N−1's compensation:

- `0001193125-25-311196`

> A reader told only that the window ends `2025-06-30` would reasonably conclude that evidence dated after it is out of scope. It is not. This section exists so that claim is measured rather than assumed.

## Source sections used

- **FY2020**: 10-K_item1_business, 10-K_item7_mdna, 8-K_8-K_whole, DEF14A_cdna, DEF14A_director_bios
- **FY2021**: 10-K_item1_business, 10-K_item7_mdna, 8-K_8-K_whole, 8-K_EX-99-1_whole, DEF14A_cdna, DEF14A_director_bios
- **FY2022**: 10-K_item1_business, 10-K_item7_mdna, 8-K_8-K_whole, 8-K_EX-99-1_whole, DEF14A_cdna, DEF14A_director_bios
- **FY2023**: 10-K_item1_business, 10-K_item7_mdna, 8-K_8-K_whole, DEF14A_cdna, DEF14A_director_bios, letter_full_text
- **FY2024**: 10-K_item1_business, 10-K_item7_mdna, 8-K_8-K_whole, DEF14A_cdna, DEF14A_director_bios, letter_full_text
- **FY2025**: 10-K_item1_business, 10-K_item7_mdna, 8-K_8-K_whole, 8-K_EX-99-1_whole, DEF14A_cdna, DEF14A_director_bios, letter_full_text

## Warnings

- FY2020 notable_language: unverified quote (DEF14A_cdna: diverges after 558 of 581 characters (96%) — the opening )
- FY2020: extraction task 'investor_qa' has no result file — run `uv run python -m equity_research.extract_facts --fy 2020 --task investor_qa`
- FY2020: extraction task 'letter' has no result file — run `uv run python -m equity_research.extract_facts --fy 2020 --task letter`
- FY2021: extraction task 'letter' has no result file — run `uv run python -m equity_research.extract_facts --fy 2021 --task letter`
- FY2022: extraction task 'letter' has no result file — run `uv run python -m equity_research.extract_facts --fy 2022 --task letter`
- FY2023: extraction task 'investor_qa' has no result file — run `uv run python -m equity_research.extract_facts --fy 2023 --task investor_qa`
- FY2024 notable_language: unverified quote (10-K_item7_mdna: diverges after 124 of 222 characters (56%) — the open)
- FY2024: extraction task 'investor_qa' has no result file — run `uv run python -m equity_research.extract_facts --fy 2024 --task investor_qa`
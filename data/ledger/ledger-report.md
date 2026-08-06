# Year ledger

Generated 2026-08-06T15:53:33Z. MORN (Morningstar, Inc.), CIK 0001289419.

Every fact carries its source filing, an exact quote from that filing, and a confidence marker. `low` means the source section's boundaries are unverified, or the quote could not be found verbatim — see `confidence_reason` on the fact. **Any claim in the outputs resting on a `low` fact must say so, or be dropped.**

Every fact and risk delta also carries a stable `id` — e.g. `SP-FY2021-471e22f5` — hashed from its claim, its evidence and its source, so an output can cite one fact rather than a whole filing. Confidence and the verification result are deliberately NOT in the hash: a judgment about a fact is not the fact, so re-verifying it later must not renumber it. 1428 ids this build, checked unique.

## Coverage

| Field | FY2021 | FY2022 | FY2023 | FY2024 | FY2025 |
|---|---|---|---|---|---|
| strategic_priorities | 9 | 16 | 18 | 18 | 17 |
| segments | 3 | 10 | 8 | 8 | 9 |
| headcount | 1 | 1 | 1 | 1 | 1 |
| leadership | 0 | 1 | 1 | 7 | 2 |
| board | 10 (10 low) | 10 (10 low) | 10 (10 low) | 10 (10 low) | 11 (11 low) |
| incentive_metrics | 7 | 7 | 8 | 7 | 7 |
| vote_results | 12 | 13 | 12 | 12 | 12 |
| events | 15 | 15 | 13 | 14 | 17 |
| notable_language | 17 | 26 | 28 | 28 | 26 |
| investor_qa | 113 | 157 (1 low) | 231 (1 low) | 163 (1 low) | 186 |
| risk_deltas (added/removed/reworded) | baseline | +5/-5/~7 | +7/-0/~12 | +1/-2/~14 | +1/-3/~17 |
| segments basis | **product areas** | **product areas** | reportable | reportable | reportable |

> **Segment counts are not comparable across the whole window.** In the years marked *product areas* the filing does not disclose reportable segments, so the `segments` field holds whatever product or business areas Item 1 describes. A change in the count between such a year and a reportable-segment year is a change in disclosure, not necessarily a re-segmentation.

## Source sections used

- **FY2021**: 10-K_item1_business, 10-K_item7_mdna, 8-K_8-K_whole, 8-K_EX-99-1_whole, DEF14A_cdna, DEF14A_director_bios, DEF14A_incentive_tables
- **FY2022**: 10-K_item1_business, 10-K_item7_mdna, 8-K_8-K_whole, DEF14A_cdna, DEF14A_director_bios, letter_full_text
- **FY2023**: 10-K_item1_business, 10-K_item7_mdna, 8-K-A_8-K-A_whole, 8-K_8-K_whole, DEF14A_cdna, DEF14A_director_bios, DEF14A_incentive_tables, letter_full_text
- **FY2024**: 10-K_item1_business, 10-K_item7_mdna, 8-K_8-K_whole, 8-K_EX-99-1_whole, 8-K_EX-99-2_whole, DEF14A_cdna, DEF14A_director_bios, letter_full_text
- **FY2025**: 10-K_item1_business, 10-K_item7_mdna, 8-K_8-K_whole, 8-K_EX-99-1_whole, DEF14A_cdna, DEF14A_director_bios, letter_full_text

## Warnings

- FY2021: extraction task 'letter' has no result file — run src/extract_facts.py --fy 2021 --task letter
- FY2022 investor_qa: unverified quote (8-K_8-K_whole: not found in the source section)
- FY2023 investor_qa: unverified quote (8-K_8-K_whole: diverges after 205 of 217 characters (94%) — the openin)
- FY2024 investor_qa: unverified quote (8-K_8-K_whole: diverges after 69 of 209 characters (33%) — the opening)
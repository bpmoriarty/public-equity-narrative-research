# Year ledger

Generated 2026-08-05T16:30:04Z. MORN (Morningstar, Inc.), CIK 0001289419.

Every fact carries its source filing, an exact quote from that filing, and a confidence marker. `low` means the source section's boundaries are unverified, or the quote could not be found verbatim — see `confidence_reason` on the fact. **Any claim in the outputs resting on a `low` fact must say so, or be dropped.**

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
| risk_deltas (added/removed/reworded) | baseline | +5/-5/~7 | +7/-0/~12 | +1/-2/~14 | +1/-3/~17 |
| segments basis | **product areas** | **product areas** | reportable | reportable | reportable |

> **Segment counts are not comparable across the whole window.** In the years marked *product areas* the filing does not disclose reportable segments, so the `segments` field holds whatever product or business areas Item 1 describes. A change in the count between such a year and a reportable-segment year is a change in disclosure, not necessarily a re-segmentation.

## Source sections used

- **FY2021**: 10-K_item1_business, 10-K_item7_mdna, 8-K_8-K_whole, DEF14A_cdna, DEF14A_director_bios, DEF14A_incentive_tables
- **FY2022**: 10-K_item1_business, 10-K_item7_mdna, 8-K_8-K_whole, DEF14A_cdna, DEF14A_director_bios, letter_full_text
- **FY2023**: 10-K_item1_business, 10-K_item7_mdna, 8-K-A_8-K-A_whole, 8-K_8-K_whole, DEF14A_cdna, DEF14A_director_bios, DEF14A_incentive_tables, letter_full_text
- **FY2024**: 10-K_item1_business, 10-K_item7_mdna, 8-K_8-K_whole, DEF14A_cdna, DEF14A_director_bios, letter_full_text
- **FY2025**: 10-K_item1_business, 10-K_item7_mdna, 8-K_8-K_whole, DEF14A_cdna, DEF14A_director_bios, letter_full_text

## Warnings

- FY2021: extraction task 'letter' has no result file — run src/extract_facts.py --fy 2021 --task letter
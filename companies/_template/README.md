# This directory is the starting point for a new company, copied by
#     uv run pipeline init <TICKER>
#
# It is NOT a company itself: paths.py skips any directory under companies/
# whose name begins with an underscore, so nothing here is ever mistaken for
# something to research.
#
# company.toml is derived from MORN's, with the three company-specific values
# blanked and the fiscal-year window set to placeholder zeros. Every comment is
# MORN's, because those comments are most of the file's value.
#
# KEEPING IT CURRENT
# tests/test_repo_hygiene.py asserts this template and every real company's
# company.toml have the same TABLES and KEYS. Add a setting to one and not the
# other and the suite fails — which is the point. A template that has silently
# fallen behind produces a config missing a key, and the failure lands on
# whoever starts the next company rather than on whoever changed the schema.

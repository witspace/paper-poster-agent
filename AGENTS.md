# Maintaining Paper Poster Agent

Write Markdown in plain language. Show the result first, then explain how to
try it. Keep public docs and screenshots free of personal machine information.
Use concrete, positive descriptions and measured claims.

Preserve paper facts, source assets and traceable evidence. Conference rules
must apply to the exact year and track; keep optional printing services separate.
Never commit user papers, projects, API credentials or local temporary files.
Use the synthetic demo for offline tests. Build public showcases from published
papers with verified reuse permission and source attribution. Keep user papers,
figures, research titles, institutional branding and identity out of public
examples, screenshots, source bundles and release artifacts.

Human approval belongs to the exact current version. Changes invalidate it.
Automated roles may propose visual changes but cannot approve for the user.
Keep changes local and reversible; publish only when explicitly requested.

Run `python -m unittest discover -s tests -v`. Browser tests use real Chromium
and reopen PDF exports independently. API contract tests use mocks; never run
paid API calls as part of tests. Keep the CLI, README, contract and skill in sync.

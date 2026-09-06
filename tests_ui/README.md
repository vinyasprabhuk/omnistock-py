# UI Regression Suite (real browser, live deployment)

Runs against a real deployed instance via Playwright + the system's
installed Google Chrome (Playwright's own bundled Chromium download
doesn't support this host's macOS version -- every test launches via
`--browser-channel=chrome`). This is separate from `tests/`, which
exercises the Flask app in-process with no real browser and no network.

**Run this after every deployment to the test environment.**

## One-time setup

```bash
.venv/bin/pip install playwright pytest-playwright
```

(Chrome must already be installed on the machine running this -- no
`playwright install` needed since we use the system browser via
`channel="chrome"`.)

## Configuration

Everything is environment variables -- **no credentials are ever
hardcoded in this suite**, since it's committed to git.

| Variable | Required | Notes |
|---|---|---|
| `UI_TEST_BASE_URL` | No (defaults to `https://test.inventory.mokshamveg.com`) | Refuses to run against anything that looks like production (must contain `test.`) |
| `UI_TEST_ADMIN_USER` / `UI_TEST_ADMIN_PASS` | Yes, for most tests | |
| `UI_TEST_KITCHEN_USER` / `UI_TEST_KITCHEN_PASS` | Yes, for Kitchen flows | |
| `UI_TEST_STORE_USER` / `UI_TEST_STORE_PASS` | No | STORE-role coverage skips cleanly without it |
| `UI_TEST_MANAGER_USER` / `UI_TEST_MANAGER_PASS` | No | same |
| `UI_TEST_VIEWER_USER` / `UI_TEST_VIEWER_PASS` | No | same |
| `UI_TEST_DEPTLEAD_USER` / `UI_TEST_DEPTLEAD_PASS` | No | same |

A role whose env vars aren't set has its tests **skip**, not fail.

Copy `.env.local.example` to `.env.local` (gitignored) and fill in real
values, then:

```bash
cd tests_ui
source .env.local
../.venv/bin/python -m pytest -v --browser-channel=chrome
```

## What this suite creates

Every test uses a **unique-per-run date** (today + ~500-800 days,
randomized per run -- see `conftest.unique_date()`) so re-running this
suite never collides with real data or with a previous run's leftover
Approved/Issued records. Nothing is deleted automatically.

**This is throwaway test data, but it does accumulate** on the test
database (`KitchenRequirement`, `Purchase`, `ProductionLog`, `Wastage`
rows dated far in the future). Periodically wipe it:

```sql
-- Run against the TEST instance/dev.db only, never production:
DELETE FROM KitchenRequirementItem WHERE requirementId IN
  (SELECT id FROM KitchenRequirement WHERE date > '2027-01-01');
DELETE FROM KitchenRequirement WHERE date > '2027-01-01';
DELETE FROM PurchaseItem WHERE purchaseId IN
  (SELECT id FROM Purchase WHERE date > '2027-01-01');
DELETE FROM Purchase WHERE date > '2027-01-01';
DELETE FROM ProductionLog WHERE date > '2027-01-01';
DELETE FROM Wastage WHERE date > '2027-01-01';
```

## What is and isn't covered

- **Covered deeply**: Kitchen Requirement full lifecycle (draft/submit
  gating, one-per-day, approve/issue/reject, edit-with-reason, Daily
  Tracker gating), Purchases (manual + bulk, GST/Bill No), Intent
  generation and the Intent -> Stock Issue -> Tracker bridge,
  Production/Wastage/Variance, role-based route access for every role
  with credentials configured.
- **Covered as a smoke test only** (loads without error, not every
  business rule): Dashboard, Master Inventory, Recipe, Admin hub.
- **Cannot be tested from here by design**: the incoming-invoice
  webhook's actual ingestion (`POST /webhooks/purchase-invoice`) is
  localhost-only on the server -- a request from wherever this suite
  runs will always get a 403 (confirmed as a passing negative test, not
  a gap). To exercise real ingestion, run a POST from the server's own
  terminal, then this suite's `test_purchases_webhook.py` review-UI
  tests will pick up the resulting pending invoice.
- **STORE/MANAGER/VIEWER/DEPARTMENT_LEAD role coverage** depends on
  those env vars being set; without them, `test_nav_access.py` skips
  those roles' checks rather than silently passing or failing.

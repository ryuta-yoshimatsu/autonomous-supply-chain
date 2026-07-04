# Digital Twin Explorer (Databricks App)

Streamlit app that visualizes all five agentic-supply-chain digital twins and lets users
filter and drill down into any series' metric time-series.

- **Twins:** Demand, Inventory, Procurement, Production, Distribution.
- **Reads:** `mickmickstableaws_catalog.monitoring.*_twin_current` and `*_twin_metrics_timeseries`
  via a Databricks **SQL warehouse** (analytical access; no data copied).
- **Auth:** **user authorization (on-behalf-of-user)** — queries run as the logged-in user via
  the forwarded `x-forwarded-access-token`, so Unity Catalog permissions are enforced per user.
  Falls back to the SDK `Config()` CLI profile when run locally. Requires the app's `sql`
  user-auth scope (configured on the app) and workspace user-auth enablement.

## Layout
```
twin_explorer/
  app.py            # Streamlit UI (generic; driven by twins.py)
  twins.py          # per-twin config: tables, keys, filters, KPIs, display + chart columns
  backend.py        # SQL warehouse data access (cached)
  app.yaml          # Databricks Apps config (command + resource/env)
  requirements.txt
```

## Configuration
`app.yaml` expects:
- a SQL warehouse resource bound under the key **`sql_warehouse`** (injected as `DATABRICKS_WAREHOUSE_ID`),
- `TWIN_CATALOG` / `TWIN_SCHEMA` (default `mickmickstableaws_catalog` / `monitoring`).

## Run locally
```bash
export DATABRICKS_WAREHOUSE_ID=<warehouse-id>
export TWIN_CATALOG=mickmickstableaws_catalog TWIN_SCHEMA=monitoring
pip install -r requirements.txt
streamlit run app.py
```
(Local auth uses your `databricks` CLI profile / `DATABRICKS_CONFIG_PROFILE`.)

## Deploy
```bash
databricks apps create twin-explorer
databricks sync . /Workspace/Users/<you>/twin_explorer
databricks apps deploy twin-explorer --source-code-path /Workspace/Users/<you>/twin_explorer
```
Then add a SQL warehouse resource (key `sql_warehouse`) to the app and set the **`sql`**
user-auth scope:
```bash
databricks apps update twin-explorer --json '{"name":"twin-explorer","user_api_scopes":["sql"],"resources":[{"name":"sql_warehouse","sql_warehouse":{"id":"<warehouse-id>","permission":"CAN_USE"}}]}'
```
Because queries run on-behalf-of the user, each user needs their own UC access to the
`monitoring` tables (no service-principal data grants required).

## Extending
Add or adjust a twin in `twins.py` (tables, keys, filters, KPIs, charts) — the UI is generic.

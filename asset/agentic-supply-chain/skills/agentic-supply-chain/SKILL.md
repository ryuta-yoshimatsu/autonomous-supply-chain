---
name: agentic-supply-chain
description: >-
  Guide a data team to build an agentic supply chain on Databricks for their own
  business — digital twins, KPI/control tower, events, planning engines, and a governed
  agent. Use when the user wants to build, scaffold, or extend a supply-chain monitoring,
  planning, or agentic-orchestration solution on Databricks, or mentions digital twins,
  control tower, demand/inventory/procurement/production/distribution twins, or
  agentic supply chain.
---

# Agentic Supply Chain (Orchestrator)

This is the entry point for building an **agentic supply chain** on Databricks. It sequences
the work, captures the key decisions, and points to the per-stage notebooks. It is a
**guided build**, not a configurable product: you keep stable interfaces and write your own
business logic at the marked extension points.

## Mental model

Closed loop: `PLAN → EXECUTE/SOURCE → MONITOR → RESPOND → ↻ re-plan`, built on five
business **digital twins**: demand, procurement, inventory/material flow, production,
distribution/fulfillment.

The twins are the **state layer**. Everything downstream (KPIs, dashboards, events,
planning engines, agent) reads from the twins, not from raw source tables.

## Core principles (do not violate)

- **Source/gold is read-only — one exception.** All derived state goes to a separate schema
  (default `monitoring`). The sole exception is `gold.demandplan`: the demand forecast is a
  canonical planning input, so Step 3 populates that gold table directly.
- **Agentic, not autonomous.** The agent diagnoses, recommends, simulates, and asks for
  approval. Consequential actions require a human gate.
- **Stable core, pluggable logic.** Config only for enumerable variation (source/column
  mapping, thresholds, cadence). Business logic (KPIs, event rules, planning policies, agent
  tools) lives in code with extension points.
- **Gate actions on data freshness.** If the relevant twin's data is stale or incomplete,
  the agent stops at diagnosis and escalation rather than acting.

## Build order

Copy this checklist and track progress:

```
- [x] Step 1: Foundation — monitoring schema
- [x] Step 2: Data profiling & gap analysis — map sources, profile, assess readiness, find gaps
- [x] Step 3: Generate demand forecast (optional — only if a demand forecast is missing)
- [x] Step 4: Digital twin state layer (demand, inventory, procurement, production, distribution)
- [x] Step 5: KPI / control tower / twin views (metric views + AI/BI dashboard + Genie + network app)
- [ ] Step 6: Events + alerts
- [ ] Step 7: Planning engines
- [ ] Step 8: Plan-of-record + scenario store (Lakebase)
- [ ] Step 9: Agentic orchestration
```

### Step 1 — Foundation (do before anything else)
Create the derived schema. (The shared `supply_chain_events` inbox is added later, in Step 6,
alongside event detection.)
Notebook: `notebooks/00_setup_monitoring_schema.ipynb`.

### Step 2 — Data profiling & gap analysis
Map each source table to the canonical role and profile it (row counts, date span, empties,
freshness). This tells you what is ready, what is empty (e.g. an existing-but-empty forecast
table), and what must be synthesized. Do this before forecasting or building any twin.
Notebook: `notebooks/01_source_mapping_and_readiness_assessment.ipynb`.

### Step 3 — Generate demand forecast (optional)
The demand forecast is an **input** to the Demand Twin and everything downstream. **Skip this
step if a populated demand forecast already exists** (check Step 2). Run it only when the
forecast is missing or empty — e.g. a target table exists but has no rows.
Notebook: `notebooks/02_generate_demand_forecast.ipynb`.
Use a Databricks-native forecasting approach (distributed per series). **Do not** use
`ai_forecast` or AutoML — use a pluggable model function so teams can swap the model.

### Step 4 — Digital twin state layer
Build five separate twins, **one notebook per twin**, in this order (each is independently
runnable and schedulable):

```
- [ ] 03_demand_twin.ipynb         -> demand_twin_current        + demand_twin_metrics_timeseries
- [ ] 04_inventory_twin.ipynb      -> inventory_twin_current     + inventory_twin_metrics_timeseries
- [ ] 05_procurement_twin.ipynb    -> procurement_twin_current   + procurement_twin_metrics_timeseries
- [ ] 06_production_twin.ipynb      -> production_twin_current    + production_twin_metrics_timeseries
- [ ] 07_distribution_twin.ipynb   -> distribution_twin_current  + distribution_twin_metrics_timeseries
- [ ] 08_relationship_layer.ipynb  -> v_network_nodes            + v_network_edges (graph views)
```

Start with **demand** then **inventory** (inventory connects everything), then procurement,
production, distribution.

**Reproducible per-twin procedure** (follow for every twin notebook):
1. **Config cell** — `source_*` / `target_*` / `monitoring_schema` widgets, plus a source
   column mapping block (`COL_*`) and a `REFRESH_ID`. Only this cell changes per business.
2. **Build inputs** — read from `gold` (+ other twins/forecast where the twin *consumes*,
   never redefines, their metrics) into temp views. Exclude rejected/irrelevant rows.
3. **`<twin>_twin_current`** — one row per the twin's natural key (the series/entity grain),
   carrying that twin's owned metrics (see "Twin ownership"), context, freshness
   (`as_of_date`, `source_max_event_date`), and `refresh_id` / `generated_at`.
4. **`<twin>_twin_metrics_timeseries`** — curated per-period metrics for the twin (trends,
   anomaly, plan-vs-actual), **not** a blind full copy of current. Include a `period_type`
   where past vs forward (forecast/projection) coexist.
5. **Write** both with `mode("overwrite")` + `option("overwriteSchema","true")` — twins are
   **rebuilt deterministically from source each run (idempotent)**. Add a table `COMMENT`.
6. **Verify** — sample `current` and show timeseries row counts by `period_type`.

**Conventions:** pure SQL/DataFrame (serverless-safe — no `.cache()`/`.persist()`); read
`gold`, write `monitoring`; keep the canonical output columns stable, change only how they
are computed; mark business logic with `# TODO — EXTEND for your business`.

Status: **all five twins done** (`03_demand` / `04_inventory` / `05_procurement` /
`06_production` / `07_distribution`).

### Step 5 — KPI / control tower / twin views
Derive KPIs from the twins (not raw source). Build dashboards + Genie + **direct twin views**
so users can inspect twin state, history, dependencies, and risk — not only KPIs.

**KPI layer — DONE.** Three governed surfaces, each with a reproducible notebook (source of truth).
Deploy against `<your-profile>`. NOTE: the workspace MCP server config
(`.cursor/mcp.json`) was repointed from profile `aws` (wrong workspace) to `<your-profile>`;
if MCP tools aren't reachable, reload the MCP server or use the CLI/SDK as the notebooks do.
1. **Metric views** — `notebooks/09_kpi_metric_views.ipynb` →
   `monitoring.{demand,inventory,procurement,production,distribution}_metrics`. UC metric views
   (`CREATE OR REPLACE VIEW ... WITH METRICS LANGUAGE YAML`) over each `*_twin_current`, with dimensions
   (material/group/plant/channel/supplier) and `MEASURE()` KPIs (OTIF, fill rate, backlog, stockouts,
   bottlenecks, yield, WMAPE, ...). Reusable by dashboard, Genie, and alerts. Needs DBR 17.2+/serverless.
2. **AI/BI dashboard** "Supply Chain Control Tower" — `notebooks/10_control_tower_dashboard.ipynb`
   (deploys via SDK `POST /api/2.0/lakeview/dashboards` then `/published`). 7 datasets (tested first),
   cross-twin KPI counters + per-domain bar charts + detail tables. Rules: **test every dataset SQL
   before deploying**; widget `fields[].name` must equal `encodings.fieldName`.
3. **Genie Space** "Supply Chain Digital Twins" — `notebooks/11_genie_space.ipynb` (builds the
   `serialized_space`: `version: 2`, `data_sources.tables` [**sorted by identifier**],
   `instructions.text_instructions`; creates via `POST /api/2.0/genie/spaces`). Points at the 10 twin
   tables (`*_twin_current` + `*_twin_metrics_timeseries`) with tailored guidance (grain per twin,
   rate 0-1 vs pct 0-100, risk flags, data caveats).

**Twin network views (interactive graph + node drilldown) — DONE (Option C).** The twins are
exposed as one typed graph and the app lets users drill into any node's operational data.
1. **Relationship layer (views-first, in `monitoring`)** — notebook `notebooks/08_relationship_layer.ipynb`:
   - `v_network_nodes` — typed nodes (`RAW_MATERIAL`/`FINISHED_GOOD` [materials split by type:
     ROH/HIBE vs FERT/HALB/HAWA-or-produced, `node_id` stays `MATERIAL:<matnr>`], `SUPPLIER`, `PLANT`,
     `WORK_CENTRE`, `CHANNEL`, `CUSTOMER`, `REGION`), each carrying its twin `status`
     (GREEN/AMBER/RED) + `metric_json`.
   - `v_network_edges` — typed edges (`SUPPLIES`, `COMPONENT_OF` [BOM], `PRODUCED_AT`, `STOCKED_AT`,
     `ROUTED_THROUGH`, `SHIPS_TO`, `SOLD_TO`), carrying `weight` (volume) + `attrs_json` (lead time / OTIF / share).
   - Plain UC **views** over `gold` + the twins (live, no copy). Column comments declared inline in
     the `CREATE VIEW` header. Shared graph API for the app, Genie, and the agent.
   - Current shape (21-material demo): **92 nodes / 206 edges, 0 dangling**.
2. **App (Twin Explorer) "Network" tab** (`apps/twin_explorer/network.py`) using **`streamlit-agraph`**:
   - **Layered layout:** nodes are placed in fixed twin columns (physics off, small deterministic
     jitter), ordered upstream → downstream — **Procurement · Raw materials · Production · Finished
     goods · Distribution · Demand** — chosen so edges flow (mostly) left → right. Each column has an
     in-canvas header (`HEADER:<col>` text nodes, ignored on click). Node colour = twin `status`,
     shape = node type (finished goods drawn larger than raw).
   - **Inventory is not a column.** `PLANT` nodes + `PRODUCED_AT`/`STOCKED_AT` edges are excluded
     (`EXCLUDE_TYPES`); inventory levels surface on the **MATERIAL** node instead — they set its
     RED/AMBER/GREEN status, appear in the hover tooltip (`on_hand`, `min_days_of_cover`), and get an
     "Inventory" tab in the click drilldown.
   - **Material-centric ego graph** (default): pick a material → its 1–3-hop neighbourhood.
   - **Domain networks** (toggle): presets over edge types (Source / Make / Stock / Deliver / Whole).
   - **Click-to-drill:** `agraph()` returns the clicked node id → `backend.node_drilldown()` shows that
     node's `metric_json` + its `_twin_current` rows (per relevant twin, tabbed). Selection persists
     in `st.session_state["net_selected"]`.
3. **Data limits:** distribution edges resolve to ship-to **region** (no outlet/DC network — missing
   `distribution_network_master`); `ROUTED_THROUGH` uses the header primary work centre only (no full
   routing master); `SOLD_TO` uses the per-series top customer; BOM edges from `gold.billofmaterials`.

> **Fix applied while building this (2026-07):** the production twin joined work centres on
> `productionorders.PrimaryWorkCentre_ARBID_Item`, which is **entirely NULL** in the source. The
> correct key is the header field `productionordersheader.PrimaryWorkCentre_ARBID`
> (matches `workcentres.WorkCentreObjectID_OBJID`). `06_production_twin.ipynb` now joins on the
> header field, so `primary_work_centre` / `is_bottleneck` populate and `ROUTED_THROUGH` edges exist.

### Step 6 — Events + alerts
Convert KPI/twin abnormalities into one shared `supply_chain_events` table (not per-twin
event tables). Route by function, severity, owner, status.

### Step 7 — Planning engines
Inventory policy → MRP → finite production scheduling → distribution planning → scenarios.
Heuristic/MRP-first; add targeted optimization (e.g. OR-Tools) on high-value trade-offs.

### Step 8 — Plan-of-record + scenario store
Use Lakebase (Postgres) for mutable plan/scenario/approval/agent-workflow state, mirrored to
Delta for analytics/audit. Lifecycle: draft → simulated → recommended → approved → committed
→ monitored → superseded.

### Step 9 — Agentic orchestration
Deploy a Model Serving agent with **narrow governed tools** (read state, run scenario,
draft action, request approval, commit approved action). Trace with MLflow. Enforce the
guardrails below.

## Key decisions (recommended defaults)

| Decision | Default | Why |
|----------|---------|-----|
| Twin storage | Delta in Unity Catalog | Analytical scans, history, dashboards, governance |
| Plan / agent workflow state | Lakebase (Postgres) + Delta mirror | Mutable, transactional, app-driven |
| Twin granularity | five separate twins | Business clarity, ownership, domain agent tools |
| Relationship/network objects | views first, materialize later | Avoid premature complexity |
| Events | one shared `supply_chain_events` | Single inbox for agents/alerts |
| Refresh | scheduled near-real-time (e.g. 30 min) | Check freshness before acting |
| Forecasting | pluggable Databricks-native model | No `ai_forecast`/AutoML; swappable |

## Twin ownership (avoid duplicating metrics)

- **Demand Twin** owns demand and forecast (firm/open demand, backlog, forecast, error, volatility).
- **Procurement Twin** owns inbound supplier state (POs, receipts, OTIF, lead time, risk).
  Reliability rates (OTIF / on-time / in-full) are computed **line-level** by default; a
  **quantity-weighted** variant (weight each PO line by quantity) is an optional extension.
- **Inventory Twin** owns stock position, availability, days-of-cover, projections, ATP.
- **Production Twin** owns manufacturing execution/capacity (WIP, yield/scrap, work-centre load, bottleneck).
  Caveats: quality percents (yield/scrap/first-pass) are **unweighted** item-level averages
  (qty-weighted is an optional extension); header metrics (cost variance, schedule adherence,
  on-time start, lead-time hours) are averaged across items; `open_order_count` counts an order
  open if any item is undelivered; `primary_work_centre` is representative and `is_bottleneck`
  is the OR across work centres; lead-time figures are **recorded actuals**, not a scheduler
  (finite scheduling needs the missing routing master + setup matrix). Facts filtered to
  `AUTYP='10'` / not-deleted; current = last 365 days by production date, time-series = full history.
- **Distribution Twin** owns outbound fulfillment (deliveries, OTIF, fill rate, fulfillment risk).
  Caveats: `fill_rate` is qty-weighted but on-time/in-full/OTIF/partial rates are **line-level**
  (qty-weighted OTIF is an optional extension); `otif_rate` treats NULL on-time as not-on-time
  while `on_time_rate` excludes NULLs; `avg_transit_days` is a derived estimate, not carrier data;
  current windows by delivery-creation date, time-series buckets by goods-issue date. Coverage is
  limited by delivery data (only a few materials — see readiness).

Other twins may **consume** these values but must not redefine them.

## Agent guardrails

- Check twin/source freshness before recommending or acting.
- Require human approval for: committing plans, changing schedules, expediting POs, sending
  supplier/customer messages.
- Every recommendation cites evidence: KPI deviation, impacted entities, root-cause
  hypothesis, scenario comparison, expected service/cost impact.
- Fail-safe: if data is stale, policy params are missing, or a solver fails — stop at
  diagnosis and escalation; do not invent a plan or act.

## Adapting to a new business

1. Set your source catalog/schema and table/column mapping in each notebook's Config cell.
2. Keep the canonical twin output columns stable; change only how they are computed.
3. Replace business logic at `# TODO — EXTEND for your business` markers (KPI formulas,
   event rules, planning policies, agent tools).
4. Use the CoffCoff fill-ins (`mickmickstableaws_catalog.gold`) as a worked example.

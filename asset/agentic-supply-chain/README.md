# Agentic Supply Chain on Databricks — Build Asset

## What is an agentic supply chain?

An agentic supply chain runs a continuous **sense → reason → recommend → act (with approval)** loop, where AI agents work directly on your own governed data to detect risks, diagnose root causes, simulate options, and drive decisions across demand, procurement, inventory, production, and distribution. Instead of static reports that tell you *what* happened, it tells you *what is about to go wrong, why, and what to do about it* — and then helps you act.

This is fundamentally different from a conventional supply-chain SaaS suite, which is a closed, generic, black-box engine your data must be copied into, configured around a vendor's fixed model, and consumed through per-seat licensing. Here, everything is built **on your lakehouse**: your data never leaves your governance perimeter, the planning logic is **tailored to your business** rather than forced into someone else's template, and analytics, planning, and action are **unified in one platform** with AI-native reasoning.

**Control and transparency are the core of the design.** Every signal, recommendation, and action is traceable end-to-end — the agent cites the data it used, the root cause it inferred, the scenarios it compared, and the expected impact, all recorded as durable, queryable records. Consequential moves never happen silently: they pass through a human approval gate, and if data is stale or incomplete the agent stops and escalates rather than guessing. You keep full ownership of the data, the models, and the decision rules, and you can inspect or override any step.

For enterprises, this means owning your data and your decisions, adapting at the speed of your business instead of a vendor's release cycle, avoiding lock-in, and turning planning from a periodic batch exercise into a living, explainable, always-on capability that the whole organization can trust.

---

This is a distributable **build kit** that guides a data team to create their own agentic supply chain on Databricks for their specific business. It combines **guidance, runnable scaffolding, and a worked reference example**.

## What this asset is


| Part                         | What it gives you                                                                              | Where                     |
| ---------------------------- | ---------------------------------------------------------------------------------------------- | ------------------------- |
| **Skills**                   | The expertise: decisions, sequencing, conventions, pitfalls. Followed by you or your AI agent. | `skills/`                 |
| **Template notebooks**       | Runnable Databricks notebooks with sensible defaults + clearly marked extension points.        | `notebooks/`              |
| **Reference implementation** | The same notebooks filled in for the "CoffCoff" coffee roastery (SAP S/4HANA gold layer).      | this repo / `gold` schema |


## The architecture you will build

A closed loop: `PLAN → EXECUTE/SOURCE → MONITOR → RESPOND → ↻ re-plan`, built on five
business **digital twins**:

1. Demand / Customer
2. Procurement
3. Inventory / Material Flow
4. Production
5. Distribution / Fulfillment

On top of the twins: a control-tower layer (dashboards, twin views, Genie), a shared events layer, planning engines, a plan-of-record store, and a governed agent.

## Why this architecture

- **Digital twins as a shared state layer.** Every business question — "are we about to stock out?", "is this supplier slipping?", "is this work centre overloaded?" — needs the same trustworthy view of current state. Building five twins once, then having dashboards, alerts, planning, and the agent all read from them, avoids duplicated, inconsistent logic and gives you one version of the truth.
- **A closed loop, not a one-way pipeline.** Plans drift the moment reality changes. Feeding deviations from `MONITOR` back into `PLAN` is what turns this from static reporting into a system that continuously re-plans and responds.
- **Separation of source, state, and decisions.** Source/gold stays read-only; derived state, plans, and agent actions live in their own layers. This keeps your system of record clean and auditable, and lets you rebuild or change the derived layers without risk to source data.
- **Layered so value comes early.** Each step is useful on its own: twins + control tower already deliver monitoring and root-cause analysis before any optimization or agent exists. You are never forced into a big-bang rollout.
- **Built for governance and trust.** Routing every recommendation and action through the events layer, the plan-of-record store, and a human approval gate makes the whole loop transparent, controllable, and safe to put in front of operators.
- **Right tool for each job.** Analytical state lives in the lakehouse (scale, history, governance); mutable operational state — plans, approvals, agent workflow — lives in an OLTP store, so each layer performs and scales as intended.

## Build order

```text
1. Foundation: monitoring schema
2. Data profiling & gap analysis: map sources, profile data, assess readiness, find gaps
3. Generate the demand forecast (optional — only if a demand forecast is missing)
4. Digital twin state layer (demand, inventory, procurement, production, distribution)
5. KPI / control tower / twin views
6. Events + alerts
7. Planning engines
8. Plan-of-record + scenario store (Lakebase)
9. Agentic orchestration
```

Step 2 is essential: before forecasting or building twins, profile every source table
(existence, row counts, date span, empties, freshness) and map it to the canonical model, so
you know exactly what is ready, what is missing, and what must be synthesized.

## Folder layout

```text
asset/agentic-supply-chain/
  README.md
  skills/
    agentic-supply-chain/        # orchestrator skill (start here)
      SKILL.md
    ... (per-stage skills added incrementally)
  notebooks/
    00_setup_monitoring_schema.ipynb
    01_source_mapping_and_readiness_assessment.ipynb
    02_generate_demand_forecast.ipynb
    03_planning_config.ipynb           (monitoring.planning_config - single source of tunable params; run BEFORE the twins)
    04_demand_twin.ipynb
    05_inventory_twin.ipynb
    06_procurement_twin.ipynb
    07_production_twin.ipynb
    08_distribution_twin.ipynb
    09_relationship_layer.ipynb        (v_network_nodes / v_network_edges graph views + v_material_bom_edges planning BOM)
    10_kpi_metric_views.ipynb          (governed UC metric views per twin)
    11_control_tower_dashboard.ipynb   (AI/BI Lakeview control-tower dashboard)
    12_genie_space.ipynb               (Genie Space over the twin tables)
    13_events.ipynb                    (monitoring.events - cross-twin detection layer)
    14_inventory_policy.ipynb          (monitoring.inventory_policy - conformal reorder point; writes recommended_action onto events)
    15_mrp.ipynb                       (monitoring.mrp_plan - time-phased weekly MRP: applies nb 14 order-up-to per week + multi-level BOM explosion -> planned orders)
    ... (per-stage notebooks added incrementally)
    (02 also emits monitoring.demand_forecast_error_sets - conformal calibration for 14)
  apps/
    twin_explorer/                     (Streamlit app: per-twin explorer + Network graph tab)
```

## How to use it

1. Read `skills/agentic-supply-chain/SKILL.md` (the orchestrator). It tells you the order,
  the decisions, and which skill/notebook to use at each step.
2. Open the notebooks in order, starting with `00_...`. Each notebook has a **Config** cell
  at the top — set your catalog/schema/source mapping there.
3. Run against your own source tables. Where business logic differs, follow the
  `# TODO — EXTEND for your business` markers.
4. Use the CoffCoff fill-ins as a worked example.

## Conventions (every build produces)

- A derived schema (default name `monitoring`) — source/gold stays **read-only**, with one
  exception: the demand forecast populates `gold.demandplan` (a canonical planning input).
- Canonical twin tables: `*_twin_current` and `*_twin_metrics_timeseries`.
- Shared IDs threaded across layers (`event_id`, `forecast_run_id`,
`recommendation_id`, `plan_version_id`, `agent_trace_id`, …) so events stay traceable.

## Reference implementation (CoffCoff)

- Source: `mickmickstableawscoff_catalog.gold` (SAP S/4HANA-style gold layer).
- Note: `gold.demandplan` exists but is **empty** — which is exactly why step 0 generates the
forecast first. This is the typical real-world starting condition.


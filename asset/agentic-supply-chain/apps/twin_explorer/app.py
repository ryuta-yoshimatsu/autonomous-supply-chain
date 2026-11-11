"""Digital Twin Explorer — Streamlit app over the agentic supply chain monitoring layer.

Visualizes all five digital twins (Demand, Inventory, Procurement, Production, Distribution)
and lets users filter and drill down into any series' metric time-series.
"""

import altair as alt
import pandas as pd
import streamlit as st

import backend
import network
from twins import TWINS

st.set_page_config(page_title="Digital Twin Explorer", page_icon="🔭", layout="wide")


def kpi_value(df: pd.DataFrame, kpi: dict):
    agg = kpi["agg"]
    if agg == "count":
        return f"{len(df):,}"
    col = kpi.get("col")
    if col not in df.columns or df[col].dropna().empty:
        return "—"
    series = pd.to_numeric(df[col], errors="coerce")
    val = series.sum() if agg == "sum" else series.mean()
    if pd.isna(val):
        return "—"
    return kpi.get("fmt", "{:,.2f}").format(val)


def render_filters(df: pd.DataFrame, filter_cols: list) -> pd.DataFrame:
    present = [c for c in filter_cols if c in df.columns]
    if not present:
        return df
    cols = st.columns(len(present))
    out = df
    for i, col in enumerate(present):
        options = sorted([v for v in df[col].dropna().unique().tolist()])
        with cols[i]:
            chosen = st.multiselect(col, options, default=[], key=f"flt_{col}")
        if chosen:
            out = out[out[col].isin(chosen)]
    return out


def _pretty_series(col: str) -> str:
    return col.replace("_qty", "").replace("_", " ").strip().title()


def render_band_chart(ts_reset: pd.DataFrame, spec: dict):
    """One chart: `lines` as coloured lines + `band` (lower, upper) as a shaded interval."""
    lower, upper = spec.get("band", [None, None])
    lines = [c for c in spec.get("lines", []) if c in ts_reset.columns]
    x = alt.X("period_start:T", title=None)
    layers = []

    if lower in ts_reset.columns and upper in ts_reset.columns:
        band_df = ts_reset[["period_start", lower, upper]].copy()
        band_df[lower] = pd.to_numeric(band_df[lower], errors="coerce")
        band_df[upper] = pd.to_numeric(band_df[upper], errors="coerce")
        band_df = band_df.dropna(subset=[lower, upper])
        if not band_df.empty:
            layers.append(
                alt.Chart(band_df).mark_area(opacity=0.22, color="#f59e0b").encode(
                    x=x,
                    y=alt.Y(f"{lower}:Q", title="qty"),
                    y2=f"{upper}:Q",
                    tooltip=[alt.Tooltip("period_start:T", title="period"),
                             alt.Tooltip(f"{lower}:Q", title="lower", format=",.0f"),
                             alt.Tooltip(f"{upper}:Q", title="upper", format=",.0f")],
                )
            )

    if lines:
        long = ts_reset[["period_start", *lines]].copy()
        for c in lines:
            long[c] = pd.to_numeric(long[c], errors="coerce")
        long = long.melt(id_vars="period_start", value_vars=lines,
                         var_name="series", value_name="qty").dropna(subset=["qty"])
        long["series"] = long["series"].map(_pretty_series)
        domain = [_pretty_series(c) for c in lines]
        rng = ["#2563eb", "#d97706", "#16a34a", "#9333ea"][:len(domain)]
        layers.append(
            alt.Chart(long).mark_line(strokeWidth=2).encode(
                x=x,
                y=alt.Y("qty:Q", title="qty"),
                color=alt.Color("series:N", title=None,
                                scale=alt.Scale(domain=domain, range=rng),
                                legend=alt.Legend(orient="bottom")),
                tooltip=[alt.Tooltip("period_start:T", title="period"),
                         alt.Tooltip("series:N", title="series"),
                         alt.Tooltip("qty:Q", title="qty", format=",.0f")],
            )
        )

    if not layers:
        st.info("No data for this chart.")
        return
    st.altair_chart(alt.layer(*layers).properties(height=340).resolve_scale(y="shared"),
                    use_container_width=True)


def render_drilldown(twin_key: str, cfg: dict, df: pd.DataFrame, user_id: str, token):
    st.subheader("Drill down — series time-series")
    if df.empty:
        st.info("No rows match the current filters.")
        return

    keys = cfg["keys"]
    sel = {}
    cols = st.columns(len(keys))
    subset = df
    for i, k in enumerate(keys):
        opts = sorted(subset[k].dropna().unique().tolist()) if k in subset.columns else []
        with cols[i]:
            val = st.selectbox(k, opts, key=f"dd_{twin_key}_{k}")
        sel[k] = val
        if val is not None:
            subset = subset[subset[k] == val]

    label_col = cfg.get("label_col")
    if label_col and label_col in df.columns and not subset.empty:
        st.caption(f"{label_col}: {subset.iloc[0][label_col]}")

    where = backend.where_from_keys(sel)
    ts = backend.load_timeseries(cfg["timeseries"], where, user_id, token)
    if ts.empty:
        st.info("No time-series rows for this selection.")
        return

    ts["period_start"] = pd.to_datetime(ts["period_start"])
    ts = ts.sort_values("period_start").set_index("period_start")

    specs = cfg.get("charts", [])
    band_specs = [s for s in specs if s.get("type") == "band"]
    line_specs = [s for s in specs if s.get("type") != "band"]
    ts_reset = ts.reset_index()

    for spec in band_specs:
        st.markdown(f"**{spec['title']}**")
        render_band_chart(ts_reset, spec)

    if line_specs:
        chart_cols = st.columns(min(len(line_specs), 3))
        for i, spec in enumerate(line_specs):
            present = [c for c in spec["cols"] if c in ts.columns]
            if not present:
                continue
            with chart_cols[i % len(chart_cols)]:
                st.markdown(f"**{spec['title']}**")
                data = ts[present].apply(pd.to_numeric, errors="coerce")
                st.line_chart(data, height=240)

    with st.expander("Raw time-series rows"):
        st.dataframe(ts.reset_index(), use_container_width=True, hide_index=True)


def render_twin(twin_key: str, user_id: str, token):
    cfg = TWINS[twin_key]
    st.header(f"{cfg.get('icon', '')} {twin_key} Twin")

    try:
        current = backend.load_current(cfg["current"], user_id, token)
    except Exception as e:  # surface connection / permission errors clearly
        st.error(f"Could not load `{cfg['current']}`: {type(e).__name__}: {e}")
        st.json(backend.diagnostics(token))
        return

    with st.sidebar:
        st.markdown("### Filters")
    # filters in main area (compact)
    filtered = render_filters(current, cfg.get("filters", []))

    # KPI cards
    kpis = cfg.get("kpis", [])
    if kpis:
        cards = st.columns(len(kpis))
        for i, kpi in enumerate(kpis):
            cards[i].metric(kpi["label"], kpi_value(filtered, kpi))

    # Current-state table
    st.subheader("Current state")
    display_cols = [c for c in cfg.get("display", []) if c in filtered.columns] or list(filtered.columns)
    st.dataframe(filtered[display_cols], use_container_width=True, hide_index=True)
    st.caption(f"{len(filtered):,} of {len(current):,} rows")

    st.divider()
    render_drilldown(twin_key, cfg, filtered, user_id, token)


def render_events(user_id: str, token):
    st.header("🚨 Events")
    st.caption(
        "Cross-twin detected abnormalities from `monitoring.events`. "
        "Recommended actions are filled by the planning engine (coming next)."
    )
    try:
        ev = backend.load_events(user_id, token)
    except Exception as e:
        st.error(f"Could not load events: {type(e).__name__}: {e}")
        st.json(backend.diagnostics(token))
        return
    if ev.empty:
        st.success("No events detected.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Events", f"{len(ev):,}")
    c2.metric("High", int((ev["severity"] == "HIGH").sum()))
    c3.metric("Medium", int((ev["severity"] == "MEDIUM").sum()))
    c4.metric("Open", int((ev["status"] == "open").sum()))

    filtered = render_filters(ev, ["function", "severity", "status", "event_type"])

    cols = [c for c in ["severity", "function", "event_type", "entity_label", "plant", "channel",
                        "title", "detail", "owner", "status", "recommended_action"]
            if c in filtered.columns]
    st.dataframe(filtered[cols], use_container_width=True, hide_index=True)
    st.caption(f"{len(filtered):,} of {len(ev):,} events")

    st.divider()
    st.subheader("Event drilldown")
    if filtered.empty:
        st.info("No events match the current filters.")
        return

    labels = {r["event_id"]: f"[{r['severity']}] {r['title']}" for _, r in filtered.iterrows()}
    eid = st.selectbox("Event", list(labels.keys()), format_func=lambda x: labels[x])
    row = filtered[filtered["event_id"] == eid].iloc[0]

    st.markdown(f"**{row['title']}**")
    st.caption(f"{row['function']} · {row['event_type']} · severity {row['severity']} · "
               f"owner {row['owner']} · status {row['status']}")
    st.write(f"Detail: {row['detail']}")
    ra = row.get("recommended_action")
    if ra:
        st.success(f"Recommended action: {ra}")
    else:
        st.info("No recommended action yet — the planning engine will populate this.")

    prefix = {"MATERIAL": "MATERIAL", "SUPPLIER": "SUPPLIER"}.get(row.get("entity_type"))
    if prefix and row.get("entity_id"):
        node_id = f"{prefix}:{row['entity_id']}"
        with st.spinner("Loading affected entity's twin rows…"):
            sections = backend.node_drilldown(node_id, user_id, token)
        if sections:
            st.markdown(f"**Affected {row['entity_type'].lower()}: {row['entity_label']}**")
            tabs = st.tabs(list(sections.keys()))
            for tab, (title, df) in zip(tabs, sections.items()):
                with tab:
                    st.dataframe(df, use_container_width=True, hide_index=True)


def main():
    st.title("🔭 Digital Twin Explorer")
    user_id, token = backend.get_user()
    st.caption(
        f"Agentic supply chain monitoring layer — `{backend.CATALOG}.{backend.SCHEMA}`. "
        "Explore the twin network or drill into any single twin."
    )
    st.sidebar.caption(f"Signed in as: {user_id}")
    view = st.sidebar.radio("View", ["🕸️ Network", "🔭 Twins", "🚨 Events"])
    if view == "🕸️ Network":
        network.render_network(user_id, token)
    elif view == "🚨 Events":
        render_events(user_id, token)
    else:
        twin_key = st.sidebar.radio("Digital twin", list(TWINS.keys()),
                                    format_func=lambda k: f"{TWINS[k].get('icon','')} {k}")
        render_twin(twin_key, user_id, token)


if __name__ == "__main__":
    main()

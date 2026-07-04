"""Network (twin graph) tab for the Digital Twin Explorer.

Renders the relationship layer (monitoring.v_network_nodes / v_network_edges) as an interactive
graph via streamlit-agraph. Two modes:
  * Material ego graph  — pick a material, see its neighbourhood (suppliers, components, plant,
    work centre, ship-to region, top customer) out to N hops.
  * Domain network      — a whole-network view scoped to a set of edge types (sourcing, make,
    inventory, deliver).
Clicking any node drills into that node's twin state + operational rows.
"""

import hashlib
import json
import pandas as pd
import streamlit as st

import backend

try:
    from streamlit_agraph import agraph, Node, Edge, Config
    _AGRAPH = True
except Exception:  # component not installed (e.g. local dev without the dep)
    _AGRAPH = False

STATUS_COLOR = {"RED": "#e5484d", "AMBER": "#f5a623", "GREEN": "#30a46c", "UNKNOWN": "#8b8d98"}
TYPE_SHAPE = {"RAW_MATERIAL": "dot", "FINISHED_GOOD": "dot", "SUPPLIER": "triangle",
              "WORK_CENTRE": "star", "CHANNEL": "hexagon", "CUSTOMER": "diamond", "REGION": "box"}
TYPE_SIZE = {"RAW_MATERIAL": 18, "FINISHED_GOOD": 28, "SUPPLIER": 18, "WORK_CENTRE": 18,
             "CHANNEL": 16, "CUSTOMER": 14, "REGION": 20}

# Each node type belongs to a twin "column"; columns are ordered upstream (left) -> downstream
# (right): raw materials -> production -> finished goods -> distribution -> demand, with suppliers
# feeding raw materials. Order chosen so every edge type flows (mostly) left-to-right.
# Materials are split by type in v_network_nodes: RAW_MATERIAL (ROH/HIBE) vs FINISHED_GOOD
# (FERT/HALB/HAWA or anything produced in the BOM); node_id stays 'MATERIAL:<matnr>'.
# Inventory (PLANT) is intentionally NOT a column: inventory levels are exposed on the material
# node instead (status colour + hover tooltip + the "Inventory" drilldown tab).
LAYER = {
    "SUPPLIER": (0, "Procurement"),
    "RAW_MATERIAL": (1, "Raw materials"),
    "WORK_CENTRE": (2, "Production"),
    "FINISHED_GOOD": (3, "Finished goods"),
    "REGION": (4, "Distribution"),
    "CHANNEL": (5, "Demand"),
    "CUSTOMER": (5, "Demand"),
}
# Node types kept out of the graph (their info is exposed via node hover / click drilldown).
EXCLUDE_TYPES = {"PLANT"}
COL_LABEL = {}
for _t, (_c, _lbl) in LAYER.items():
    COL_LABEL[_c] = _lbl
COL_ORDER = [COL_LABEL[c] for c in sorted(COL_LABEL)]
COL_GAP = 380      # horizontal spacing between twin columns (wide -> graph stretches across)
ROW_GAP = 72       # vertical spacing between nodes in a column
_STATUS_ORDER = {"RED": 0, "AMBER": 1, "GREEN": 2, "UNKNOWN": 3}

# Edges to/from PLANT (PRODUCED_AT, STOCKED_AT) are excluded with the Inventory column; the
# remaining edge types all flow material -> downstream and render left-to-right.
DOMAINS = {
    "Whole network": ["SUPPLIES", "COMPONENT_OF", "ROUTED_THROUGH", "SHIPS_TO", "SOLD_TO"],
    "Source (suppliers & BOM)": ["SUPPLIES", "COMPONENT_OF"],
    "Make (routing)": ["ROUTED_THROUGH"],
    "Deliver (fulfillment & customers)": ["SHIPS_TO", "SOLD_TO"],
}


def _jitter(seed: str, amp: int) -> int:
    """Deterministic per-node offset in [-amp, amp] so columns aren't razor-straight but layout
    stays stable across reruns."""
    h = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)
    return (h % (2 * amp + 1)) - amp


def _short(text: str, n: int = 26) -> str:
    text = str(text)
    return text if len(text) <= n else text[: n - 1] + "\u2026"


def _tooltip(row: pd.Series) -> str:
    parts = [f"{row['node_type']}  \u2022  {row['status']}", str(row["label"])]
    try:
        metrics = json.loads(row.get("metric_json") or "{}")
    except Exception:
        metrics = {}
    for k, v in metrics.items():
        if v is None:
            continue
        if isinstance(v, float):
            v = f"{v:,.2f}"
        parts.append(f"{k}: {v}")
    return "\n".join(parts)


def _ego(edges_df: pd.DataFrame, center: str, depth: int):
    """BFS out from `center`; returns (edges subset, set of node ids reached)."""
    frontier = {center}
    seen = {center}
    keep = []
    for _ in range(depth):
        mask = edges_df["source_id"].isin(frontier) | edges_df["target_id"].isin(frontier)
        sub = edges_df[mask]
        keep.extend(sub.index.tolist())
        reached = set(sub["source_id"]) | set(sub["target_id"])
        frontier = reached - seen
        seen |= reached
        if not frontier:
            break
    return edges_df.loc[sorted(set(keep))], seen


def _inject_canvas_style():
    """Give the graph's component iframe a soft gradient background + rounded border so the
    interactive (zoom/pan) area is visually distinct from the scrollable page around it."""
    st.markdown(
        """
        <style>
        iframe[title="streamlit_agraph.agraph"],
        div[data-testid="stCustomComponent"] iframe {
            background: linear-gradient(135deg, #f7f9fc 0%, #eef2ff 45%, #dde6fb 100%) !important;
            border: 1px solid #d5dcea !important;
            border-radius: 14px !important;
            box-shadow: inset 0 0 46px rgba(70, 100, 190, 0.07),
                        0 1px 3px rgba(15, 23, 42, 0.06) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _legend():
    chips = "".join(
        f"<span style='display:inline-block;margin:2px 8px 2px 0;'>"
        f"<span style='color:{c};font-size:16px'>&#9679;</span> {name}</span>"
        for name, c in STATUS_COLOR.items() if name != "UNKNOWN")
    shapes = " &nbsp; ".join(f"{t.replace('_', ' ').title()}" for t in TYPE_SHAPE)
    st.caption("Node colour = twin health status")
    st.markdown(f"<div style='font-size:13px'>{chips}</div>", unsafe_allow_html=True)
    st.caption(f"Node types: {shapes}")


def _render_graph(nodes_df: pd.DataFrame, edges_df: pd.DataFrame, show_edge_labels: bool,
                  height: int = 640):
    """Column layout: nodes placed at fixed coords by twin column (upstream left -> downstream
    right), physics disabled, with an in-canvas header label per column."""
    node_ids = set(nodes_df["node_id"])
    df = nodes_df.copy()
    df["_col"] = df["node_type"].map(lambda t: LAYER.get(t, (99, t))[0])
    df["_srt"] = df["status"].map(lambda s: _STATUS_ORDER.get(s, 3))

    cols_present = sorted(df["_col"].unique())
    col_groups = {c: df[df["_col"] == c].sort_values(["_srt", "label"]) for c in cols_present}
    max_n = max((len(g) for g in col_groups.values()), default=1)
    header_y = -((max_n - 1) / 2) * ROW_GAP - ROW_GAP * 1.6

    g_nodes = []
    for c, grp in col_groups.items():
        n = len(grp)
        start = -((n - 1) / 2) * ROW_GAP
        x = c * COL_GAP
        for i, (_, r) in enumerate(grp.iterrows()):
            g_nodes.append(Node(
                id=r["node_id"],
                label=_short(r["label"]),
                size=TYPE_SIZE.get(r["node_type"], 16),
                shape=TYPE_SHAPE.get(r["node_type"], "dot"),
                color=STATUS_COLOR.get(r["status"], STATUS_COLOR["UNKNOWN"]),
                title=_tooltip(r),
                x=int(x + _jitter(r["node_id"] + "x", 34)),
                y=int(start + i * ROW_GAP + _jitter(r["node_id"] + "y", 18)),
            ))
        g_nodes.append(Node(
            id=f"HEADER:{c}",
            label=COL_LABEL.get(c, "Other"),
            shape="text",
            x=int(x), y=int(header_y),
            physics=False,
            font={"size": 22, "bold": True, "color": "#374151"},
        ))

    g_edges = []
    for _, e in edges_df.iterrows():
        if e["source_id"] not in node_ids or e["target_id"] not in node_ids:
            continue
        g_edges.append(Edge(
            source=e["source_id"],
            target=e["target_id"],
            label=e["edge_type"] if show_edge_labels else "",
        ))
    config = Config(width="100%", height=height, directed=True, physics=False,
                    hierarchical=False, nodeHighlightBehavior=True,
                    highlightColor="#c8d6ff", collapsible=False,
                    link={"labelProperty": "label", "renderLabel": show_edge_labels},
                    edges={"smooth": {"type": "cubicBezier", "forceDirection": "horizontal",
                                      "roundness": 0.35}},
                    interaction={"zoomSpeed": 0.3, "zoomView": True, "dragView": True,
                                 "dragNodes": True})
    return agraph(nodes=g_nodes, edges=g_edges, config=config)


def _render_drilldown(node_id: str, nodes_df: pd.DataFrame, user_id: str, token):
    row = nodes_df[nodes_df["node_id"] == node_id]
    if row.empty:
        st.info("Selected node is not in the current graph.")
        return
    row = row.iloc[0]
    node_type, _ = backend.parse_node(node_id)
    color = STATUS_COLOR.get(row["status"], STATUS_COLOR["UNKNOWN"])
    st.markdown(
        f"### <span style='color:{color}'>&#9679;</span> {row['label']}",
        unsafe_allow_html=True)
    st.caption(f"{node_type}  \u2022  status **{row['status']}**  \u2022  `{node_id}`")

    try:
        metrics = json.loads(row.get("metric_json") or "{}")
    except Exception:
        metrics = {}
    metrics = {k: v for k, v in metrics.items() if v is not None}
    if metrics:
        cols = st.columns(min(len(metrics), 4))
        for i, (k, v) in enumerate(metrics.items()):
            val = f"{v:,.2f}" if isinstance(v, float) else f"{v}"
            cols[i % len(cols)].metric(k.replace("_", " "), val)

    with st.spinner("Loading operational rows\u2026"):
        sections = backend.node_drilldown(node_id, user_id, token)
    if not sections:
        st.info("No operational twin rows for this node.")
        return
    tabs = st.tabs(list(sections.keys()))
    for tab, (title, df) in zip(tabs, sections.items()):
        with tab:
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.caption(f"{len(df):,} row(s)")


def render_network(user_id: str, token):
    st.header("\U0001f578\ufe0f Twin network")
    if not _AGRAPH:
        st.error("`streamlit-agraph` is not installed in this environment.")
        return
    _inject_canvas_style()

    try:
        nodes_df = backend.load_nodes(user_id, token)
        edges_df = backend.load_edges(user_id, token)
    except Exception as e:
        st.error(f"Could not load the relationship layer: {type(e).__name__}: {e}")
        st.json(backend.diagnostics(token))
        return

    # Drop excluded node types (e.g. PLANT/inventory) and any edges touching them.
    excluded = set(nodes_df.loc[nodes_df["node_type"].isin(EXCLUDE_TYPES), "node_id"])
    nodes_df = nodes_df[~nodes_df["node_type"].isin(EXCLUDE_TYPES)].reset_index(drop=True)
    edges_df = edges_df[~edges_df["source_id"].isin(excluded)
                        & ~edges_df["target_id"].isin(excluded)].reset_index(drop=True)

    # Health summary across the whole graph.
    counts = nodes_df["status"].value_counts().to_dict()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Nodes", f"{len(nodes_df):,}")
    c2.metric("Edges", f"{len(edges_df):,}")
    c3.metric("At risk (RED)", f"{counts.get('RED', 0):,}")
    c4.metric("Watch (AMBER)", f"{counts.get('AMBER', 0):,}")

    mode = st.radio(
        "View", ["Material ego graph", "Domain network"], horizontal=True,
        help=("**Material ego graph** centres on one material and shows its supply-chain "
              "neighbourhood. **Domain network** shows the whole graph scoped to a set of "
              "relationship types."))
    show_labels = st.checkbox("Show edge labels", value=(mode == "Material ego graph"))

    materials = (nodes_df[nodes_df["node_id"].str.startswith("MATERIAL:")]
                 .sort_values("label")[["node_id", "label", "node_type"]])
    mat_map = dict(zip(materials["node_id"], materials["label"]))

    if mode == "Material ego graph":
        # One dropdown grouped into Raw materials / Finished goods with divider header rows.
        raw_ids = materials.loc[materials["node_type"] == "RAW_MATERIAL", "node_id"].tolist()
        fin_ids = materials.loc[materials["node_type"] == "FINISHED_GOOD", "node_id"].tolist()
        HDR_RAW, HDR_FIN = "__hdr_raw__", "__hdr_fin__"
        opt_labels = dict(mat_map)
        opt_labels[HDR_RAW] = "\u2500\u2500 Raw materials \u2500\u2500"
        opt_labels[HDR_FIN] = "\u2500\u2500 Finished goods \u2500\u2500"
        options, default_idx = [], 0
        if raw_ids:
            options += [HDR_RAW] + raw_ids
        if fin_ids:
            options += [HDR_FIN] + fin_ids
        default_idx = next((i for i, o in enumerate(options)
                            if not o.startswith("__hdr")), 0)

        left, right = st.columns([3, 1])
        with left:
            center = st.selectbox("Material", options, index=default_idx,
                                  format_func=lambda o: opt_labels.get(o, o),
                                  help="The material to place at the centre of the graph. "
                                       "The divider rows are just group labels.")
        if center == HDR_RAW:
            center = raw_ids[0]
        elif center == HDR_FIN:
            center = fin_ids[0]
        with right:
            depth = st.slider(
                "Hops", 1, 3, 1,
                help=("**Hops** = how many relationship steps out from the selected material to "
                      "include.\n\n"
                      "\u2022 **1 hop** — its direct neighbours: suppliers, component materials, "
                      "the work centre it's produced at, ship-to region, and top customer.\n\n"
                      "\u2022 **2 hops** — also the neighbours of those nodes (e.g. a supplier's "
                      "other materials, a component's own components).\n\n"
                      "\u2022 **3 hops** — expands one step further out."))
        sub_edges, reached = _ego(edges_df, center, depth)
        sub_nodes = nodes_df[nodes_df["node_id"].isin(reached)]
        st.caption(f"{len(sub_nodes)} nodes \u00b7 {len(sub_edges)} edges within {depth} hop(s) "
                   f"of {mat_map.get(center, center)}")
    else:
        domain = st.selectbox("Domain", list(DOMAINS.keys()))
        edge_types = st.multiselect("Edge types", DOMAINS["Whole network"],
                                    default=DOMAINS[domain])
        sub_edges = edges_df[edges_df["edge_type"].isin(edge_types)]
        keep = set(sub_edges["source_id"]) | set(sub_edges["target_id"])
        sub_nodes = nodes_df[nodes_df["node_id"].isin(keep)]
        st.caption(f"{len(sub_nodes)} nodes \u00b7 {len(sub_edges)} edges")

    _legend()
    st.caption("Columns (upstream \u2192 downstream): " + "  \u2192  ".join(COL_ORDER))

    # Full-width graph on top ...
    clicked = _render_graph(sub_nodes, sub_edges, show_labels, height=560)
    if clicked and not str(clicked).startswith("HEADER:"):
        st.session_state["net_selected"] = clicked

    # ... node meta-information / drilldown below it.
    st.divider()
    selected = st.session_state.get("net_selected")
    if selected:
        _render_drilldown(selected, nodes_df, user_id, token)
    else:
        st.info("Click a node to drill into its twin state and operational rows.")

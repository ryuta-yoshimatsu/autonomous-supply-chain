"""Data access for the Digital Twin Explorer app.

Reads the monitoring.*_twin_current / *_twin_metrics_timeseries tables via a Databricks
SQL warehouse using **user authorization** (on-behalf-of-user): queries run as the logged-in
user via the forwarded `x-forwarded-access-token`. Falls back to SDK Config() (your CLI
profile) when run locally. No tokens are hardcoded, logged, or cached as cache keys.
"""

import os
import pandas as pd
import streamlit as st
from databricks import sql
from databricks.sdk.core import Config

CATALOG = os.getenv("TWIN_CATALOG", "mickmickstableawscoff_catalog")
SCHEMA = os.getenv("TWIN_SCHEMA", "monitoring")
WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "")

_HTTP_PATH = f"/sql/1.0/warehouses/{WAREHOUSE_ID}"


def fq(table: str) -> str:
    return f"{CATALOG}.{SCHEMA}.{table}"


def _sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def where_from_keys(keys: dict) -> str:
    return " AND ".join(f"{col} = {_sql_literal(val)}" for col, val in keys.items())


def get_user():
    """Return (user_id, token). Token is the forwarded user token when deployed; None locally."""
    headers = getattr(st.context, "headers", None) or {}
    token = headers.get("x-forwarded-access-token")
    user_id = (headers.get("x-forwarded-email")
               or headers.get("x-forwarded-preferred-username")
               or "local-user")
    return user_id, token


def diagnostics(token: str | None) -> dict:
    try:
        host = Config().host
    except Exception as e:
        host = f"<config error: {e}>"
    return {"host": host, "warehouse_id_set": bool(WAREHOUSE_ID),
            "warehouse_id": WAREHOUSE_ID, "http_path": _HTTP_PATH,
            "user_token_present": bool(token)}


def _hostname() -> str:
    # databricks-sql expects a bare hostname; Config().host includes the https:// scheme.
    host = Config().host or ""
    return host.replace("https://", "").replace("http://", "").rstrip("/")


def _connect(token: str | None):
    cfg = Config()
    if token:
        return sql.connect(server_hostname=_hostname(), http_path=_HTTP_PATH, access_token=token)
    # Local fallback: use the developer's CLI profile.
    return sql.connect(server_hostname=_hostname(), http_path=_HTTP_PATH,
                       credentials_provider=lambda: cfg.authenticate)


# `_token` is prefixed with "_" so Streamlit excludes it from the cache key; results are keyed
# by (query, user_id) so different users never share cached rows.
@st.cache_data(ttl=300, show_spinner=False)
def run_query(query: str, user_id: str, _token: str | None) -> pd.DataFrame:
    print(f"[twin] run_query user={user_id} diag={diagnostics(_token)} q={query[:80]}", flush=True)
    try:
        conn = _connect(_token)
        try:
            with conn.cursor() as cur:
                cur.execute(query)
                cols = [c[0] for c in cur.description]
                rows = cur.fetchall()
        finally:
            conn.close()
    except Exception as e:
        import traceback
        print(f"[twin] run_query ERROR {type(e).__name__}: {e} | args={e.args} | "
              f"cause={repr(getattr(e, '__cause__', None))} | ctx={repr(getattr(e, '__context__', None))}",
              flush=True)
        traceback.print_exc()
        raise
    return pd.DataFrame([list(r) for r in rows], columns=cols)


def load_current(table: str, user_id: str, token: str | None) -> pd.DataFrame:
    return run_query(f"SELECT * FROM {fq(table)}", user_id, token)


def load_timeseries(table: str, where: str, user_id: str, token: str | None) -> pd.DataFrame:
    return run_query(f"SELECT * FROM {fq(table)} WHERE {where} ORDER BY period_start", user_id, token)


# ---- Relationship layer (twin network graph) ------------------------------------------------

def load_events(user_id: str, token: str | None) -> pd.DataFrame:
    return run_query(
        f"SELECT * FROM {fq('events')} "
        "ORDER BY CASE severity WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END, function, event_type",
        user_id, token)


def load_nodes(user_id: str, token: str | None) -> pd.DataFrame:
    return run_query(f"SELECT * FROM {fq('v_network_nodes')}", user_id, token)


def load_edges(user_id: str, token: str | None) -> pd.DataFrame:
    return run_query(f"SELECT * FROM {fq('v_network_edges')}", user_id, token)


def parse_node(node_id: str):
    """Split 'TYPE:key' into (type, key). WORK_CENTRE keys are 'plant:arbpl'."""
    node_type, _, key = node_id.partition(":")
    return node_type, key


# For each node type, the twin tables (title, table, key-column) to show on drilldown.
_DRILL = {
    "MATERIAL": [("Demand", "demand_twin_current", "material"),
                 ("Inventory", "inventory_twin_current", "material"),
                 ("Procurement", "procurement_twin_current", "material"),
                 ("Production", "production_twin_current", "material"),
                 ("Distribution", "distribution_twin_current", "material")],
    "SUPPLIER": [("Procurement", "procurement_twin_current", "supplier")],
    "PLANT": [("Inventory", "inventory_twin_current", "plant"),
              ("Production", "production_twin_current", "plant"),
              ("Distribution", "distribution_twin_current", "plant")],
    "CHANNEL": [("Demand", "demand_twin_current", "channel"),
                ("Distribution", "distribution_twin_current", "channel")],
    "CUSTOMER": [("Demand (as top customer)", "demand_twin_current", "top_customer_id")],
    "REGION": [("Distribution (as top ship-to)", "distribution_twin_current", "top_ship_to_region")],
}


def node_drilldown(node_id: str, user_id: str, token: str | None) -> dict:
    """Return {section_title: DataFrame} of operational twin rows for a graph node."""
    node_type, key = parse_node(node_id)
    out: dict[str, pd.DataFrame] = {}
    if node_type == "WORK_CENTRE":
        plant, _, arbpl = key.partition(":")
        where = (f"plant = {_sql_literal(plant)} AND "
                 f"primary_work_centre = {_sql_literal(arbpl)}")
        df = run_query(f"SELECT * FROM {fq('production_twin_current')} WHERE {where}", user_id, token)
        if not df.empty:
            out["Production"] = df
        return out
    for title, table, col in _DRILL.get(node_type, []):
        df = run_query(f"SELECT * FROM {fq(table)} WHERE {col} = {_sql_literal(key)}", user_id, token)
        if not df.empty:
            out[title] = df
    return out

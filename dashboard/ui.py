"""TrafficSense design system -- "civic wayfinding console".

Light, high-clarity, disciplined. The red/amber/green signal tri-colour is
reserved strictly for data (corridor impact level); a deep authoritative
navy is the structural colour. Shared so every page reads as one product.

Type:  Schibsted Grotesk (display) - Inter (UI) - IBM Plex Mono (numerics)
Signature: the corridor status rail (a transit-line-style status board).
"""
import html as _html

import pandas as pd
import streamlit as st

# --- palette -------------------------------------------------------------
PAPER = "#F6F7F9"
SURFACE = "#FFFFFF"
INK = "#14202E"
NAVY = "#1B3A5B"
STEEL = "#5E6B7E"
LINE = "#E4E7EC"

GREEN = "#2A9D63"
AMBER = "#E8930C"
RED = "#E5484D"

SIGNAL = {"Low": GREEN, "Medium": AMBER, "High": RED}

# Distinct (non-signal) hues for the score-breakdown factors.
FACTOR_COLOURS = {
    "Live speed reduction": "#1B3A5B",   # navy
    "Breakdown-risk model": "#3E7CB1",   # steel blue
    "Event context": "#E8930C",          # amber
    "Weather": "#1B9C8E",                # teal
}


def signal_colour(level: str) -> str:
    return SIGNAL.get(level, STEEL)


def _esc(s) -> str:
    return _html.escape(str(s))


# --- one-time CSS --------------------------------------------------------
def inject_css():
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Schibsted+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root {
  --paper:#F6F7F9; --surface:#FFFFFF; --ink:#14202E; --navy:#1B3A5B;
  --steel:#5E6B7E; --line:#E4E7EC; --green:#2A9D63; --amber:#E8930C; --red:#E5484D;
}

html, body, [class*="st-"], .stApp, .stMarkdown, p, span, div, label, input, button {
  font-family: 'Inter', system-ui, sans-serif;
}

/* ...but never override Streamlit's Material icon font, or icon ligatures
   (sidebar collapse arrows, etc.) render as literal text. */
[data-testid="stIconMaterial"],
.material-icons, .material-icons-outlined,
[class*="material-symbols"], [class^="material-symbols"],
span[translate="no"] {
  font-family: 'Material Symbols Rounded', 'Material Symbols Outlined',
               'Material Icons' !important;
}

.stApp { background: var(--paper); }
.block-container { padding-top: 2.4rem; max-width: 1180px; }

/* hide default streamlit chrome for a cleaner console */
#MainMenu, footer, [data-testid="stDecoration"] { visibility: hidden; }
[data-testid="stHeader"] { background: transparent; }

/* sidebar */
[data-testid="stSidebar"] { background: var(--surface); border-right: 1px solid var(--line); }
[data-testid="stSidebarNav"] a span { font-weight: 500; }

/* --- page header --- */
.ts-eyebrow {
  font-family:'IBM Plex Mono', monospace; font-size:.72rem; letter-spacing:.22em;
  text-transform:uppercase; color:var(--navy); font-weight:500; margin-bottom:.5rem;
  display:flex; align-items:center; gap:.6rem;
}
.ts-eyebrow::before {
  content:""; width:26px; height:2px; background:var(--navy); display:inline-block;
}
.ts-title {
  font-family:'Schibsted Grotesk', sans-serif; font-weight:700; color:var(--ink);
  font-size:2.5rem; line-height:1.05; letter-spacing:-.02em; margin:0;
}
.ts-sub { color:var(--steel); font-size:1rem; margin:.55rem 0 0; max-width:60ch; }
.ts-rule { height:1px; background:var(--line); margin:1.5rem 0 1.6rem; border:0; }

/* --- instrument readouts --- */
.ts-readouts { display:flex; flex-wrap:wrap; gap:14px; margin:.2rem 0 .4rem; }
.ts-readout {
  flex:1 1 150px; background:var(--surface); border:1px solid var(--line);
  border-radius:12px; padding:16px 18px; position:relative; overflow:hidden;
}
.ts-readout::before {
  content:""; position:absolute; left:0; top:0; bottom:0; width:3px; background:var(--accent,var(--navy));
}
.ts-readout-label {
  font-size:.72rem; letter-spacing:.08em; text-transform:uppercase;
  color:var(--steel); font-weight:600; margin-bottom:.35rem;
}
.ts-readout-value {
  font-family:'IBM Plex Mono', monospace; font-size:1.85rem; font-weight:600;
  color:var(--ink); line-height:1;
}
.ts-readout-sub { font-size:.78rem; color:var(--steel); margin-top:.35rem; }

/* --- corridor status rail (signature) --- */
.ts-rail { background:var(--surface); border:1px solid var(--line); border-radius:14px; padding:6px 4px; }
.ts-rail-row {
  display:flex; align-items:center; gap:14px; padding:11px 18px;
  border-bottom:1px solid var(--line);
}
.ts-rail-row:last-child { border-bottom:0; }
.ts-dot { width:11px; height:11px; border-radius:50%; flex:0 0 auto; box-shadow:0 0 0 3px rgba(0,0,0,.04); }
.ts-rail-name { flex:0 0 200px; font-weight:500; color:var(--ink); font-size:.94rem;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.ts-rail-level { flex:0 0 70px; font-size:.74rem; font-weight:600; text-transform:uppercase; letter-spacing:.04em; }
.ts-rail-bar { flex:1 1 auto; height:6px; background:#EEF1F4; border-radius:99px; overflow:hidden; }
.ts-rail-bar-fill { height:100%; border-radius:99px; }
.ts-rail-score { flex:0 0 46px; text-align:right; font-family:'IBM Plex Mono',monospace;
  font-weight:600; font-size:1.02rem; color:var(--ink); }
.ts-rail-speed { flex:0 0 96px; text-align:right; font-family:'IBM Plex Mono',monospace;
  font-size:.82rem; color:var(--steel); }

/* --- score breakdown (explainability) --- */
.ts-breakdown { background:var(--surface); border:1px solid var(--line);
  border-radius:12px; padding:14px 16px; margin-bottom:12px; }
.ts-breakdown-head { display:flex; justify-content:space-between; align-items:baseline;
  margin-bottom:.5rem; color:var(--ink); font-size:.96rem; }
.ts-breakdown-total { font-family:'IBM Plex Mono',monospace; font-weight:600; font-size:1.2rem; }
.ts-breakdown-total span { font-size:.8rem; color:var(--steel); font-weight:400; }
.ts-stack { display:flex; height:14px; border-radius:7px; overflow:hidden; background:#EEF1F4; }
.ts-stack > span { display:block; height:100%; }
.ts-legend { display:flex; flex-wrap:wrap; gap:14px; margin-top:.6rem;
  font-size:.8rem; color:var(--steel); }
.ts-legend-item { display:inline-flex; align-items:center; gap:.4rem; }
.ts-legend-item b { color:var(--ink); font-family:'IBM Plex Mono',monospace; }
.ts-legend-pip { width:9px; height:9px; border-radius:2px; display:inline-block; }

/* --- pills / badges --- */
.ts-pill {
  display:inline-flex; align-items:center; gap:.45rem; font-size:.78rem; font-weight:600;
  padding:.32rem .7rem; border-radius:99px; border:1px solid var(--line); background:var(--surface);
}
.ts-pill .ts-pip { width:7px; height:7px; border-radius:50%; }
.ts-badge {
  display:inline-block; font-size:.74rem; font-weight:600; padding:.16rem .55rem;
  border-radius:6px; color:#fff;
}

/* --- section heading --- */
.ts-section { font-family:'Schibsted Grotesk',sans-serif; font-weight:600; color:var(--ink);
  font-size:1.18rem; margin:1.7rem 0 .7rem; display:flex; align-items:center; gap:.6rem; }
.ts-section::before { content:""; width:5px; height:18px; background:var(--navy); border-radius:2px; }

/* --- buttons --- */
.stButton > button {
  border-radius:9px; font-weight:600; border:1px solid var(--line);
  padding:.5rem 1.1rem; transition:all .15s ease;
}
.stButton > button[kind="primary"] { background:var(--navy); border-color:var(--navy); }
.stButton > button[kind="primary"]:hover { background:#16314d; }

/* --- dataframe --- */
[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:12px; overflow:hidden; }

/* --- folium map framing --- */
iframe[title="streamlit_folium.st_folium"] { border:1px solid var(--line); border-radius:14px; }

/* inputs a touch softer */
[data-baseweb="input"], [data-baseweb="select"] > div { border-radius:9px; }

/* --- motion (subtle; disabled for reduced-motion) --- */
@keyframes tsFadeUp { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:none; } }
@keyframes tsGrow { from { transform:scaleX(0); } to { transform:scaleX(1); } }
.ts-readout, .ts-kpi, .ts-kpi-headline, .ts-force, .ts-why { animation:tsFadeUp .4s ease both; }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation:none !important; transition:none !important; }
}

/* --- KPI: one big headline figure + supporting instrument readouts --- */
.ts-kpi-headline {
  background:linear-gradient(180deg,#ffffff,#fbfcfd);
  border:1px solid var(--line); border-left:4px solid var(--accent,var(--navy));
  border-radius:16px; padding:26px 30px; margin-bottom:16px;
}
.ts-kpi-headline .lab { font-size:.75rem; letter-spacing:.14em; text-transform:uppercase; color:var(--steel); font-weight:600; }
.ts-kpi-headline .val { font-family:'IBM Plex Mono',monospace; font-weight:600; color:var(--ink);
  font-size:4rem; line-height:1; letter-spacing:-.02em; margin:.35rem 0 .25rem; }
.ts-kpi-headline .val span { font-size:1.5rem; color:var(--steel); margin-left:.45rem; }
.ts-kpi-headline .cap { color:var(--steel); font-size:.92rem; }

.ts-kpi-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(176px,1fr)); gap:14px; }
.ts-kpi { background:var(--surface); border:1px solid var(--line); border-radius:13px;
  padding:18px 20px; position:relative; overflow:hidden; }
.ts-kpi::before { content:""; position:absolute; left:0; top:0; bottom:0; width:3px; background:var(--accent,var(--navy)); }
.ts-kpi .lab { font-size:.72rem; letter-spacing:.08em; text-transform:uppercase; color:var(--steel); font-weight:600; }
.ts-kpi .val { font-family:'IBM Plex Mono',monospace; font-weight:600; font-size:1.9rem; color:var(--ink); line-height:1; margin-top:.45rem; }
.ts-kpi .val span { font-size:.88rem; color:var(--steel); margin-left:.25rem; }
.ts-kpi .cap { font-size:.76rem; color:var(--steel); margin-top:.45rem; }

/* --- SHAP force bars: red pushes toward High, green pulls toward Low --- */
.ts-force { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:16px 18px; }
.ts-force-row { display:grid; grid-template-columns:190px 1fr; gap:14px; align-items:center; margin:.42rem 0; }
.ts-force-meta { text-align:right; }
.ts-force-meta .f { font-size:.84rem; color:var(--ink); font-weight:500; line-height:1.15; }
.ts-force-meta .v { font-family:'IBM Plex Mono',monospace; font-size:.72rem; color:var(--steel); }
.ts-force-track { position:relative; height:24px; background:#F1F3F6; border-radius:6px; }
.ts-force-track::before { content:""; position:absolute; left:50%; top:0; bottom:0; width:1px; background:#C9D0D9; }
.ts-force-bar { position:absolute; top:4px; bottom:4px; border-radius:4px; transform-origin:var(--origin,left); animation:tsGrow .5s ease both; }
.ts-force-legend { display:flex; justify-content:space-between; font-size:.72rem; color:var(--steel); margin-top:.55rem; }

/* --- "why" rationale card --- */
.ts-why { background:var(--surface); border:1px solid var(--line); border-left:4px solid var(--accent,var(--navy));
  border-radius:12px; padding:14px 18px; margin-bottom:12px; }
.ts-why-title { font-weight:600; color:var(--ink); font-size:.96rem; margin-bottom:.5rem;
  display:flex; align-items:center; gap:.5rem; }
.ts-why-title .tag { font-family:'IBM Plex Mono',monospace; font-size:.7rem; color:var(--steel);
  border:1px solid var(--line); border-radius:5px; padding:.1rem .42rem; }
.ts-why ul { margin:0; padding-left:1.1rem; }
.ts-why li { color:var(--steel); font-size:.86rem; margin:.26rem 0; }
.ts-why li b { color:var(--ink); font-weight:600; }

/* --- timeline playback clock --- */
.ts-clock { display:flex; align-items:baseline; gap:.6rem; }
.ts-clock .t { font-family:'IBM Plex Mono',monospace; font-size:2.4rem; font-weight:600; color:var(--ink); line-height:1; }
.ts-clock .d { font-size:.78rem; color:var(--steel); text-transform:uppercase; letter-spacing:.1em; }
</style>
""",
        unsafe_allow_html=True,
    )


# --- components ----------------------------------------------------------
def header(eyebrow: str, title: str, subtitle: str = ""):
    sub = f'<p class="ts-sub">{_esc(subtitle)}</p>' if subtitle else ""
    st.markdown(
        f'<div class="ts-eyebrow">{_esc(eyebrow)}</div>'
        f'<h1 class="ts-title">{_esc(title)}</h1>{sub}'
        f'<hr class="ts-rule"/>',
        unsafe_allow_html=True,
    )


def section(title: str):
    st.markdown(f'<div class="ts-section">{_esc(title)}</div>', unsafe_allow_html=True)


def readouts(items):
    """items: list of dicts {label, value, sub?, accent?}."""
    cards = []
    for it in items:
        accent = it.get("accent", NAVY)
        sub = f'<div class="ts-readout-sub">{_esc(it["sub"])}</div>' if it.get("sub") else ""
        cards.append(
            f'<div class="ts-readout" style="--accent:{accent}">'
            f'<div class="ts-readout-label">{_esc(it["label"])}</div>'
            f'<div class="ts-readout-value">{_esc(it["value"])}</div>{sub}</div>'
        )
    st.markdown(f'<div class="ts-readouts">{"".join(cards)}</div>', unsafe_allow_html=True)


def pill(text: str, colour: str = NAVY):
    st.markdown(
        f'<span class="ts-pill"><span class="ts-pip" style="background:{colour}"></span>{_esc(text)}</span>',
        unsafe_allow_html=True,
    )


def level_badge(level: str) -> str:
    return f'<span class="ts-badge" style="background:{signal_colour(level)}">{_esc(level)}</span>'


def score_bars(corridor, total, components):
    """Explain a corridor's composite score: a single stacked bar split into
    the factors that built it, with a legend. components: list of
    {factor, points, share}."""
    total = max(total, 0.001)
    segs, legend = [], []
    for c in components:
        col = FACTOR_COLOURS.get(c["factor"], STEEL)
        w = max(0.0, c["points"]) / total * 100
        if w > 0:
            segs.append(f'<span style="width:{w}%;background:{col}" title="{_esc(c["factor"])}"></span>')
        legend.append(
            f'<span class="ts-legend-item"><span class="ts-legend-pip" style="background:{col}"></span>'
            f'{_esc(c["factor"])} <b>{c["points"]:.0f}</b></span>'
        )
    st.markdown(
        f'<div class="ts-breakdown">'
        f'<div class="ts-breakdown-head"><b>{_esc(corridor)}</b>'
        f'<span class="ts-breakdown-total">{total:.0f}<span>/100</span></span></div>'
        f'<div class="ts-stack">{"".join(segs)}</div>'
        f'<div class="ts-legend">{"".join(legend)}</div></div>',
        unsafe_allow_html=True,
    )


def barricade_marker(folium, lat, lon, priority="HIGH", popup=None):
    """A 🚧 barricade marker -- clearer than the default ban glyph. Red ring
    for HIGH, amber for MEDIUM."""
    ring = RED if priority == "HIGH" else AMBER
    html = (
        f'<div style="font-size:20px;line-height:20px;width:26px;height:26px;'
        f'display:flex;align-items:center;justify-content:center;'
        f'background:#fff;border:2px solid {ring};border-radius:50%;'
        f'box-shadow:0 1px 4px rgba(0,0,0,.3)">\U0001F6A7</div>'
    )
    return folium.Marker(
        [lat, lon],
        popup=popup,
        icon=folium.DivIcon(html=html, icon_size=(26, 26), icon_anchor=(13, 13)),
    )


def tow_truck_marker(folium, lat, lon, popup=None):
    """A 🚛 tow-truck pre-positioning marker -- navy ring to read as a staged
    resource, distinct from the red barricade rings."""
    html = (
        f'<div style="font-size:18px;line-height:18px;width:26px;height:26px;'
        f'display:flex;align-items:center;justify-content:center;'
        f'background:#fff;border:2px solid {NAVY};border-radius:50%;'
        f'box-shadow:0 1px 4px rgba(0,0,0,.3)">\U0001F69B</div>'
    )
    return folium.Marker(
        [lat, lon],
        popup=popup,
        icon=folium.DivIcon(html=html, icon_size=(26, 26), icon_anchor=(13, 13)),
    )


def corridor_rail(states, limit=None, show_speed=True):
    """Signature: transit-line status board. states: list of corridor dicts
    with corridor, impact_level, composite_score, optional tomtom speeds."""
    rows_data = sorted(states, key=lambda c: -c["composite_score"])
    if limit:
        rows_data = rows_data[:limit]
    rows = []
    for c in rows_data:
        colour = signal_colour(c["impact_level"])
        width = max(3, min(100, c["composite_score"]))
        speed = ""
        if show_speed:
            cur, free = c.get("tomtom_current_speed"), c.get("tomtom_free_flow_speed")
            txt = f"{cur}/{free} km/h" if cur is not None and free is not None else "—"
            speed = f'<span class="ts-rail-speed">{_esc(txt)}</span>'
        rows.append(
            f'<div class="ts-rail-row">'
            f'<span class="ts-dot" style="background:{colour}"></span>'
            f'<span class="ts-rail-name">{_esc(c["corridor"])}</span>'
            f'<span class="ts-rail-level" style="color:{colour}">{_esc(c["impact_level"])}</span>'
            f'<span class="ts-rail-bar"><span class="ts-rail-bar-fill" '
            f'style="width:{width}%;background:{colour}"></span></span>'
            f'<span class="ts-rail-score">{c["composite_score"]:.0f}</span>'
            f'{speed}</div>'
        )
    st.markdown(f'<div class="ts-rail">{"".join(rows)}</div>', unsafe_allow_html=True)


# --- structured tables ---------------------------------------------------
def corridor_table(states):
    df = pd.DataFrame(
        [
            {
                "Corridor": c["corridor"],
                "Impact": c["impact_level"],
                "Risk score": c["composite_score"],
                "Est. clearance": c["congestion_duration_min"],
                "Now": c.get("tomtom_current_speed"),
                "Free-flow": c.get("tomtom_free_flow_speed"),
                "Slowdown": c.get("tomtom_deviation"),
                "Source": "mock" if c.get("tomtom_is_mock") else "live",
            }
            for c in states
        ]
    )
    cfg = {
        "Corridor": st.column_config.TextColumn(width="medium"),
        "Impact": st.column_config.TextColumn(width="small"),
        "Risk score": st.column_config.ProgressColumn(
            "Risk score", min_value=0, max_value=100, format="%d"
        ),
        "Est. clearance": st.column_config.NumberColumn("Est. clearance", format="%d min"),
        "Now": st.column_config.NumberColumn("Now", format="%d km/h"),
        "Free-flow": st.column_config.NumberColumn("Free-flow", format="%d km/h"),
        "Slowdown": st.column_config.ProgressColumn(
            "Slowdown", min_value=0.0, max_value=1.0, format="%.2f"
        ),
        "Source": st.column_config.TextColumn("Feed", width="small"),
    }
    st.dataframe(df, use_container_width=True, hide_index=True, column_config=cfg)


def impact_forecast_table(corridors):
    df = pd.DataFrame(
        [
            {
                "Corridor": c["corridor"],
                "Impact": c["impact_level"],
                "Risk score": c.get("event_risk_score", 0),
                "Est. clearance": c["congestion_duration_min"],
            }
            for c in corridors
        ]
    )
    cfg = {
        "Risk score": st.column_config.ProgressColumn("Risk score", min_value=0, max_value=100, format="%d"),
        "Est. clearance": st.column_config.NumberColumn("Est. clearance", format="%d min"),
    }
    st.dataframe(df, use_container_width=True, hide_index=True, column_config=cfg)


# --- KPI / explainability / timeline components ---------------------------
KPI_ACCENTS = [NAVY, "#3E7CB1", "#1B9C8E", "#4C5FD5"]


def kpi_headline(value, unit, label, caption="", accent=NAVY):
    """The single hero figure on the Impact Dashboard -- the page's thesis."""
    st.markdown(
        f'<div class="ts-kpi-headline" style="--accent:{accent}">'
        f'<div class="lab">{_esc(label)}</div>'
        f'<div class="val">{_esc(value)}<span>{_esc(unit)}</span></div>'
        f'<div class="cap">{_esc(caption)}</div></div>',
        unsafe_allow_html=True,
    )


def kpi_hero(items):
    """Supporting instrument readouts. items: {label, value, unit?, caption?, accent?}."""
    cards = []
    for i, it in enumerate(items):
        accent = it.get("accent", KPI_ACCENTS[i % len(KPI_ACCENTS)])
        unit = f'<span>{_esc(it["unit"])}</span>' if it.get("unit") else ""
        cap = f'<div class="cap">{_esc(it["caption"])}</div>' if it.get("caption") else ""
        cards.append(
            f'<div class="ts-kpi" style="--accent:{accent}">'
            f'<div class="lab">{_esc(it["label"])}</div>'
            f'<div class="val">{_esc(it["value"])}{unit}</div>{cap}</div>'
        )
    st.markdown(f'<div class="ts-kpi-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def shap_force(contributions):
    """Diverging force plot of a model decision. contributions: list of
    {label, value, contribution, direction}. Red bars (right) push the forecast
    toward High impact; green bars (left) pull it toward Low -- the same signal
    language the rest of the console uses."""
    if not contributions:
        return
    maxabs = max(abs(c["contribution"]) for c in contributions) or 1.0
    rows = []
    for c in contributions:
        frac = abs(c["contribution"]) / maxabs * 46  # half-track max width %
        if c["direction"] == "up":
            bar = f'<span class="ts-force-bar" style="left:50%;width:{frac}%;background:{RED};--origin:left"></span>'
        else:
            bar = f'<span class="ts-force-bar" style="right:50%;width:{frac}%;background:{GREEN};--origin:right"></span>'
        rows.append(
            f'<div class="ts-force-row">'
            f'<div class="ts-force-meta"><div class="f">{_esc(c["label"])}</div>'
            f'<div class="v">{_esc(c["value"])}</div></div>'
            f'<div class="ts-force-track">{bar}</div></div>'
        )
    st.markdown(
        f'<div class="ts-force">{"".join(rows)}'
        f'<div class="ts-force-legend"><span>&larr; pulls toward Low</span>'
        f'<span>pushes toward High &rarr;</span></div></div>',
        unsafe_allow_html=True,
    )


def why_card(title, points, tag=None, accent=NAVY):
    """A 'why this recommendation' card. `points` are pre-formatted strings
    (may contain <b>...</b>); `tag` is a small monospace badge (e.g. a count)."""
    tag_html = f'<span class="tag">{_esc(tag)}</span>' if tag else ""
    lis = "".join(f"<li>{p}</li>" for p in points)
    st.markdown(
        f'<div class="ts-why" style="--accent:{accent}">'
        f'<div class="ts-why-title">{_esc(title)}{tag_html}</div>'
        f"<ul>{lis}</ul></div>",
        unsafe_allow_html=True,
    )


def timeline_clock(hour, date_str=""):
    st.markdown(
        f'<div class="ts-clock"><span class="t">{hour:02d}:00</span>'
        f'<span class="d">{_esc(date_str)}</span></div>',
        unsafe_allow_html=True,
    )


def historical_blockage_table(corridors):
    df = pd.DataFrame(
        [
            {
                "Corridor": c["corridor"],
                "Likelihood": c["likelihood"],
                "Past incidents": c["incidents"],
                "Closure rate": c["closure_rate"],
                "Avg severity": c["avg_severity"],
            }
            for c in corridors
        ]
    )
    cfg = {
        "Likelihood": st.column_config.ProgressColumn("Blockage likelihood", min_value=0.0, max_value=1.0, format="%.2f"),
        "Closure rate": st.column_config.NumberColumn("Closure rate", format="%.2f"),
    }
    st.dataframe(df, use_container_width=True, hide_index=True, column_config=cfg)


def manpower_table(plan):
    df = pd.DataFrame(
        [
            {
                "Corridor": p["corridor"],
                "Officers": p["officers"],
                "Impact": p["impact_level"],
                "Deploy by": p["deploy_by"],
            }
            for p in plan
        ]
    )
    cfg = {
        "Officers": st.column_config.NumberColumn("Officers", format="%d"),
        "Deploy by": st.column_config.TextColumn("Deploy by", width="small"),
    }
    st.dataframe(df, use_container_width=True, hide_index=True, column_config=cfg)


def optimized_plan_table(plan):
    """Optimizer allocation: officers assigned vs required, with coverage and
    the basis for each number (why that many officers)."""
    df = pd.DataFrame(
        [
            {
                "Corridor": p["corridor"],
                "Assigned": p["officers"],
                "Required": p.get("required", p["officers"]),
                "Impact": p["impact_level"],
                "Deploy by": p["deploy_by"],
                "Covered": "✓" if p.get("covered", True) else "—",
                "Why this many": p.get("rationale", ""),
            }
            for p in plan
        ]
    )
    cfg = {
        "Assigned": st.column_config.NumberColumn("Assigned", format="%d"),
        "Required": st.column_config.NumberColumn("Required", format="%d"),
        "Deploy by": st.column_config.TextColumn("Deploy by", width="small"),
        "Covered": st.column_config.TextColumn("Covered", width="small"),
        "Why this many": st.column_config.TextColumn("Why this many", width="large"),
    }
    st.dataframe(df, use_container_width=True, hide_index=True, column_config=cfg)

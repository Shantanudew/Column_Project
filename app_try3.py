import streamlit as st
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches

st.set_page_config(page_title="Column Rebar Detailer", layout="wide")
st.title("Automated Column Detailing (ETABS to ACI 318 Detail)")

# --- SIDEBAR INPUTS ---
st.sidebar.header("Column Geometry & Demand")
p = st.sidebar.number_input("ETABS Reinforcement % (p)", min_value=0.5, max_value=8.0, value=2.0, step=0.1)
B = st.sidebar.number_input("Column Width B (mm)", min_value=150, max_value=3000, value=1000, step=25)
D = st.sidebar.number_input("Column Depth D (mm)", min_value=150, max_value=3000, value=1000, step=25)
stirrup_dia = st.sidebar.selectbox("Stirrup Diameter (mm)", [8, 10, 12, 16], index=1)
cover = st.sidebar.number_input("Clear Cover (mm)", value=40, step=5)

st.sidebar.header("Bar Selection Mode")
mode = st.sidebar.radio("Optimization Mode", ["Auto-Select Best Bar & Layout", "Manual Bar Selection"])

available_dias = [12, 16, 20, 25, 32, 40]
if mode == "Manual Bar Selection":
    dia_choice = st.sidebar.selectbox("Select Bar Diameter (mm)", available_dias, index=3)  # Default 25mm
    candidate_dias = [dia_choice]
else:
    candidate_dias = available_dias

target_min_s = 55.0
target_max_s = 75.0
max_agg_size = 20.0  # Standard 20 mm coarse aggregate
min_agg_clear_s = (4.0 / 3.0) * max_agg_size  # 26.7 mm (ACI 25.2.3)

# --- STRUCTURAL DEMAND ---
Ag = B * D
Ast_req = (p * Ag) / 100.0

# --- CORE SOLVER FUNCTION ---
def solve_layout(dia, bundled=False, enforce_constructibility=True):
    a_bar = (np.pi * (dia ** 2)) / 4.0
    n_bars_needed = int(np.ceil(Ast_req / a_bar))
    if n_bars_needed < 4:
        n_bars_needed = 4
        
    if bundled:
        n_stations_needed = int(np.ceil(n_bars_needed / 2.0))
        if n_stations_needed < 4:
            n_stations_needed = 4
        # Equivalent diameter per ACI 318-19 Section 25.6.1.5
        de = np.sqrt(2.0) * dia
        min_allowable_s = max(de, min_agg_clear_s)
        min_req_cover = min(de, 50.0)  # ACI 25.6.1.6
    else:
        n_stations_needed = n_bars_needed
        de = float(dia)
        min_allowable_s = max(dia, min_agg_clear_s, 25.0)
        min_req_cover = float(dia)

    span_x = B - 2 * (cover + stirrup_dia) - dia
    span_y = D - 2 * (cover + stirrup_dia) - dia
    
    max_search = max(20, int(np.ceil(n_stations_needed / 2)) + 6)
    best = None
    min_penalty = float("inf")
    
    for Nx in range(2, max_search):
        for Ny in range(2, max_search):
            stations = 2 * Nx + 2 * Ny - 4
            if stations >= n_stations_needed:
                if bundled:
                    sx = (span_x - (Nx - 1) * (2 * dia)) / (Nx - 1)
                    sy = (span_y - (Ny - 1) * (2 * dia)) / (Ny - 1)
                else:
                    sx = (span_x - (Nx - 1) * dia) / (Nx - 1)
                    sy = (span_y - (Ny - 1) * dia) / (Ny - 1)
                
                # Check against ACI equivalent diameter spacing limit
                if sx < min_allowable_s or sy < min_allowable_s:
                    continue

                total_actual_bars = stations * (2 if bundled else 1)
                
                if enforce_constructibility:
                    spacing_mid = (target_min_s + target_max_s) / 2.0
                    penalty = abs(sx - spacing_mid) + abs(sy - spacing_mid) + (total_actual_bars - n_bars_needed) * 3
                    
                    if target_min_s <= sx <= target_max_s and target_min_s <= sy <= target_max_s:
                        penalty -= 40.0
                    elif sx < target_min_s or sy < target_min_s:
                        penalty += 100.0
                else:
                    # Minimum theoretical bars
                    penalty = (total_actual_bars - n_bars_needed) * 1000 + abs(Nx - Ny)

                if penalty < min_penalty:
                    min_penalty = penalty
                    best = {
                        "dia": dia,
                        "bundled": bundled,
                        "de": de,
                        "min_allowable_s": min_allowable_s,
                        "min_req_cover": min_req_cover,
                        "Nx": Nx,
                        "Ny": Ny,
                        "stations": stations,
                        "total_bars": total_actual_bars,
                        "Ast_provided": total_actual_bars * a_bar,
                        "p_provided": (total_actual_bars * a_bar / Ag) * 100.0,
                        "sx": sx,
                        "sy": sy,
                        "penalty": penalty
                    }
    return best

# --- INTERNAL MULTI-TIER OPTIMIZER ---
candidate_results = []

for d in candidate_dias:
    # Check raw theoretical minimum
    raw_layout = solve_layout(d, bundled=False, enforce_constructibility=False)
    if raw_layout is None:
        raw_layout = solve_layout(d, bundled=True, enforce_constructibility=False)
        
    if raw_layout is not None:
        sx = raw_layout["sx"]
        sy = raw_layout["sy"]
        # If raw spacing is inside [60, 150] mm, use it directly
        if 60.0 <= sx <= 150.0 and 60.0 <= sy <= 150.0:
            candidate_results.append(raw_layout)
        else:
            # Spacing is congested (<60mm) or too wide (>150mm), trigger optimization
            opt_layout = solve_layout(d, bundled=False, enforce_constructibility=True)
            if opt_layout is None or opt_layout["sx"] < 40.0 or opt_layout["sy"] < 40.0:
                opt_layout = solve_layout(d, bundled=True, enforce_constructibility=True)
            if opt_layout is not None:
                candidate_results.append(opt_layout)

# Select the overall best configuration
active_layout = min(candidate_results, key=lambda x: x["penalty"])
use_Bundle = active_layout["bundled"]
dia = active_layout["dia"]
de = active_layout["de"]

# --- TIE & CROSSTIE REQUIREMENTS (ACI 318 6-INCH RULE) ---
aci_threshold = 150.0
station_width = (2 * dia) if use_Bundle else dia
s_skip_x = 2 * active_layout["sx"] + station_width
s_skip_y = 2 * active_layout["sy"] + station_width

has_intermediates = (active_layout["Nx"] > 2 or active_layout["Ny"] > 2)

if not has_intermediates:
    tie_mode = "NONE"
    stride_x = 0
    stride_y = 0
    tie_advice = "Outer Master Tie alone is sufficient (4 corner bars only)."
elif active_layout["sx"] > aci_threshold or active_layout["sy"] > aci_threshold:
    tie_mode = "EVERY_BAR"
    stride_x = 1
    stride_y = 1
    tie_advice = "EVERY intermediate bar requires a crosstie (Adjacent clear spacing > 150 mm)."
elif s_skip_x > aci_threshold or s_skip_y > aci_threshold:
    tie_mode = "EVERY_BAR"
    stride_x = 1
    stride_y = 1
    tie_advice = "EVERY intermediate bar requires a crosstie (Clear distance across skipped bar > 150 mm)."
else:
    tie_mode = "ALTERNATE"
    stride_x = 2
    stride_y = 2
    tie_advice = "Alternate bars tied with crossties (Clear distance across skipped bar is <= 150 mm)."

# --- UI DASHBOARD ---
col1, col2 = st.columns([1.1, 1.2])

with col1:
    st.subheader("Design Decision Summary")
    
    st.markdown(f"**Required Steel Area ($A_{{st}}$):** `{Ast_req:.1f} mm²` &nbsp;(**{p:.2f}%**)")
    st.markdown(
        f"**Optimized Provided Area:** `{active_layout['Ast_provided']:.1f} mm²` "
        f"&nbsp;(**{active_layout['p_provided']:.2f}%**)"
    )
    st.markdown(
        f"**Reinforcement Provided:** **{active_layout['total_bars']} bars** of **#{dia} mm** "
        f"({'2-Bar Bundled' if use_Bundle else 'Single Regular Bars'})"
    )
    st.markdown(f"**Arrangement Grid:** `{active_layout['Nx']} (along B) × {active_layout['Ny']} (along D)`")
    st.markdown(f"**Clear Spacing ($s_x, s_y$):** `{active_layout['sx']:.1f} mm, {active_layout['sy']:.1f} mm`")

    # --- BUNDLE AUDIT (ACI 25.6 & 25.2.3) ---
    if use_Bundle:
        st.divider()
        st.subheader("Bundling Provisions Audit (ACI 318-19 §25.6)")
        st.info(f"**Bundle Type:** 2-Bar Bundle | **Equivalent Diameter ($d_e$):** `{de:.1f} mm` (per §25.6.1.5)")
        st.write(f"Min Allowable Spacing ($s_{{min}} = \\max(d_e, 26.7\\text{{ mm}})$): **{active_layout['min_allowable_s']:.1f} mm**")
        
        if cover < active_layout["min_req_cover"]:
            st.error(
                f"**Cover Warning (ACI §25.6.1.6):** Specified cover ({cover} mm) is less than required equivalent cover "
                f"to bundle: min($d_e$, 50 mm) = **{active_layout['min_req_cover']:.1f} mm**. Increase cover in sidebar."
            )
        else:
            st.success(f"**Cover OK (ACI §25.6.1.6):** Specified cover ({cover} mm) $\\ge$ {active_layout['min_req_cover']:.1f} mm.")

    # --- TRANSVERSE TIES ---
    st.divider()
    st.subheader("Transverse Ties (ACI 318 6-Inch Rule)")
    st.write(f"Master Tie: **#{stirrup_dia} mm** hoop")
    st.write(f"Skipped Bar Span ($B$ face): **{s_skip_x:.1f} mm**")
    st.write(f"Skipped Bar Span ($D$ face): **{s_skip_y:.1f} mm**")
    
    if tie_mode == "EVERY_BAR":
        st.error(f"Tie Rule: **{tie_advice}**")
    elif tie_mode == "ALTERNATE":
        st.warning(f"Tie Rule: **{tie_advice}**")
    else:
        st.success(f"Tie Rule: **{tie_advice}**")

# --- CROSS-SECTION CANVAS ---
with col2:
    st.subheader("Column Cross-Section View")
    fig, ax = plt.subplots(figsize=(7.5, 7.5))
    
    # Concrete Rectangle
    concrete = patches.Rectangle((0, 0), B, D, linewidth=2, edgecolor='black', facecolor='#fbfbfb')
    ax.add_patch(concrete)
    
    # Master Tie
    tie_outer_x = cover
    tie_outer_y = cover
    tie_outer_w = B - 2 * cover
    tie_outer_h = D - 2 * cover
    outer_tie = patches.Rectangle((tie_outer_x, tie_outer_y), tie_outer_w, tie_outer_h,
                                  linewidth=1.8, edgecolor='#00529B', facecolor='none')
    ax.add_patch(outer_tie)

    tie_inner_x = cover + stirrup_dia
    tie_inner_y = cover + stirrup_dia
    tie_inner_w = B - 2 * (cover + stirrup_dia)
    tie_inner_h = D - 2 * (cover + stirrup_dia)
    inner_tie = patches.Rectangle((tie_inner_x, tie_inner_y), tie_inner_w, tie_inner_h,
                                  linewidth=1.0, edgecolor='#00529B', facecolor='none', linestyle=':')
    ax.add_patch(inner_tie)
    
    # Rebar Grid Coordinates
    r = dia / 2.0
    x_min = tie_inner_x + r
    x_max = tie_inner_x + tie_inner_w - r
    y_min = tie_inner_y + r
    y_max = tie_inner_y + tie_inner_h - r
    
    xs = np.linspace(x_min, x_max, active_layout["Nx"])
    ys = np.linspace(y_min, y_max, active_layout["Ny"])
    
    # Internal Crossties
    if tie_mode in ["ALTERNATE", "EVERY_BAR"]:
        for i in range(1, len(xs) - 1, stride_x):
            ax.plot([xs[i], xs[i]], [y_min - r, y_max + r], 
                    color='#ff7f0e', linestyle='--', linewidth=1.3, zorder=2)
        for j in range(1, len(ys) - 1, stride_y):
            ax.plot([x_min - r, x_max + r], [ys[j], ys[j]], 
                    color='#ff7f0e', linestyle='--', linewidth=1.3, zorder=2)

    # Station coordinates
    stations = []
    for x in xs[1:-1]:
        stations.append((x, y_min, 'bottom'))
        stations.append((x, y_max, 'top'))
    for y in ys[1:-1]:
        stations.append((x_min, y, 'left'))
        stations.append((x_max, y, 'right'))
        
    corners = [
        (x_min, y_min, 'corner_bl'),
        (x_max, y_min, 'corner_br'),
        (x_min, y_max, 'corner_tl'),
        (x_max, y_max, 'corner_tr')
    ]
    stations.extend(corners)
    
    diag_shift = dia / np.sqrt(2)
    
    for x, y, pos in stations:
        if not use_Bundle:
            circle = patches.Circle((x, y), r, facecolor='#d62728', edgecolor='black', linewidth=1, zorder=3)
            ax.add_patch(circle)
        else:
            if pos == 'corner_bl':
                c1, c2 = (x, y), (x + diag_shift, y + diag_shift)
            elif pos == 'corner_br':
                c1, c2 = (x, y), (x - diag_shift, y + diag_shift)
            elif pos == 'corner_tl':
                c1, c2 = (x, y), (x + diag_shift, y - diag_shift)
            elif pos == 'corner_tr':
                c1, c2 = (x, y), (x - diag_shift, y - diag_shift)
            elif pos in ['bottom', 'top']:
                c1, c2 = (x - r, y), (x + r, y)
            elif pos in ['left', 'right']:
                c1, c2 = (x, y - r), (x, y + r)
                
            ax.add_patch(patches.Circle(c1, r, facecolor='#d62728', edgecolor='black', linewidth=1, zorder=3))
            ax.add_patch(patches.Circle(c2, r, facecolor='#d62728', edgecolor='black', linewidth=1, zorder=3))

    ax.set_xlim(-50, B + 50)
    ax.set_ylim(-50, D + 50)
    ax.set_aspect('equal')
    ax.axis('off')
    st.pyplot(fig)

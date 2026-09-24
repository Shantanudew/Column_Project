import streamlit as st
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches

st.set_page_config(page_title="Column Rebar Detailer", layout="wide")
st.title("Automated Column Detailing (ETABS to ACI 318 Detail)")

# --- SIDEBAR INPUTS ---
st.sidebar.header("Column Geometry & Demand")
p = st.sidebar.number_input("ETABS Reinforcement % (p)", min_value=0.5, max_value=8.0, value=2.0, step=0.1)
B = st.sidebar.number_input("Column Width B (mm)", min_value=150, max_value=3000, value=800, step=25)
D = st.sidebar.number_input("Column Depth D (mm)", min_value=150, max_value=3000, value=1000, step=25)
stirrup_dia = st.sidebar.selectbox("Stirrup Diameter (mm)", [8, 10, 12, 16], index=2)
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
        de = np.sqrt(2.0) * dia
        min_allowable_s = max(de, min_agg_clear_s)
        min_req_cover = min(de, 50.0)
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
    raw_layout = solve_layout(d, bundled=False, enforce_constructibility=False)
    if raw_layout is None:
        raw_layout = solve_layout(d, bundled=True, enforce_constructibility=False)
        
    if raw_layout is not None:
        sx = raw_layout["sx"]
        sy = raw_layout["sy"]
        if 60.0 <= sx <= 150.0 and 60.0 <= sy <= 150.0:
            candidate_results.append(raw_layout)
        else:
            opt_layout = solve_layout(d, bundled=False, enforce_constructibility=True)
            if opt_layout is None or opt_layout["sx"] < 40.0 or opt_layout["sy"] < 40.0:
                opt_layout = solve_layout(d, bundled=True, enforce_constructibility=True)
            if opt_layout is not None:
                candidate_results.append(opt_layout)

active_layout = min(candidate_results, key=lambda x: x["penalty"])
use_Bundle = active_layout["bundled"]
dia = active_layout["dia"]
de = active_layout["de"]

# --- ACI 318 VERTICAL TIE SPACING (ACI 25.7.2.1) ---
s_vert_code = min(16 * dia, 48 * stirrup_dia, B, D, 300)
# Practical rounding down to 25 mm or 50 mm increment
s_vert_practical = int(np.floor(s_vert_code / 25.0) * 25)

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
    tie_advice = "Outer Master Tie alone is sufficient."
elif active_layout["sx"] > aci_threshold or active_layout["sy"] > aci_threshold:
    tie_mode = "EVERY_BAR"
    stride_x = 1
    stride_y = 1
    tie_advice = "EVERY intermediate bar requires a crosstie (Clear spacing > 150 mm)."
elif s_skip_x > aci_threshold or s_skip_y > aci_threshold:
    tie_mode = "EVERY_BAR"
    stride_x = 1
    stride_y = 1
    tie_advice = "EVERY intermediate bar requires a crosstie (Skipped span > 150 mm)."
else:
    tie_mode = "ALTERNATE"
    stride_x = 2
    stride_y = 2
    tie_advice = "Alternate bars tied with crossties (Skipped span <= 150 mm)."

# Center-to-center pitch
cc_x = active_layout["sx"] + (2 * dia if use_Bundle else dia)
cc_y = active_layout["sy"] + (2 * dia if use_Bundle else dia)

# --- UI DASHBOARD ---
col1, col2 = st.columns([1.1, 1.3])

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
    st.markdown(f"**Center-to-Center Spacing ($c/c_x, c/c_y$):** `{cc_x:.1f} mm, {cc_y:.1f} mm`")

    if use_Bundle:
        st.divider()
        st.subheader("Bundling Provisions Audit (ACI 318-19 §25.6)")
        st.info(f"**Bundle Type:** 2-Bar Bundle | **Equivalent Diameter ($d_e$):** `{de:.1f} mm`")
        st.write(f"Min Allowable Spacing: **{active_layout['min_allowable_s']:.1f} mm**")
        if cover < active_layout["min_req_cover"]:
            st.error(f"**Cover Warning (ACI §25.6.1.6):** Cover ({cover} mm) < required {active_layout['min_req_cover']:.1f} mm.")
        else:
            st.success(f"**Cover OK (ACI §25.6.1.6):** Specified cover ({cover} mm) satisfied.")

    st.divider()
    st.subheader("Transverse Confinement & Detailing (ACI 318)")
    st.write(f"Master Outer Tie: **#{stirrup_dia} mm @ {s_vert_practical} mm c/c**")
    st.write(f"Crossties / Links: **#{stirrup_dia} mm @ {s_vert_practical} mm c/c**")
    st.write(f"Vertical Pitch Limit: **{s_vert_practical} mm** (Code Max: {s_vert_code:.0f} mm)")
    
    if tie_mode == "EVERY_BAR":
        st.error(f"Transverse Rule: **{tie_advice}**")
    elif tie_mode == "ALTERNATE":
        st.warning(f"Transverse Rule: **{tie_advice}**")
    else:
        st.success(f"Transverse Rule: **{tie_advice}**")

# --- CROSS-SECTION & DETAILING CANVAS ---
# --- CROSS-SECTION & DETAILING CANVAS ---
with col2:
    st.subheader("Column Detailing & Schedule View")
    fig, ax = plt.subplots(figsize=(10, 9))
    
    # Concrete Cross Section
    concrete = patches.Rectangle((0, 0), B, D, linewidth=2.5, edgecolor='#1e1e1e', facecolor='#fafafa', zorder=1)
    ax.add_patch(concrete)
    
    # Master Tie
    tie_ox = cover
    tie_oy = cover
    tie_ow = B - 2 * cover
    tie_oh = D - 2 * cover
    outer_tie = patches.Rectangle((tie_ox, tie_oy), tie_ow, tie_oh,
                                  linewidth=2.0, edgecolor='#00529B', facecolor='none', zorder=2)
    ax.add_patch(outer_tie)

    # Master Tie 135 deg seismic hook indicator (Top-Right Corner)
    hook_len = 6 * stirrup_dia + 20
    ax.plot([tie_ox + tie_ow - stirrup_dia, tie_ox + tie_ow - hook_len],
            [tie_oy + tie_oh - stirrup_dia, tie_oy + tie_oh - hook_len],
            color='#00529B', linewidth=2.0, zorder=2)

    # Coordinates Setup
    tie_ix = cover + stirrup_dia
    tie_iy = cover + stirrup_dia
    tie_iw = B - 2 * (cover + stirrup_dia)
    tie_ih = D - 2 * (cover + stirrup_dia)
    
    r = dia / 2.0
    x_min = tie_ix + r
    x_max = tie_ix + tie_iw - r
    y_min = tie_iy + r
    y_max = tie_iy + tie_ih - r
    
    xs = np.linspace(x_min, x_max, active_layout["Nx"])
    ys = np.linspace(y_min, y_max, active_layout["Ny"])
    
    # Internal Crossties with alternating 90/135 deg end hooks
    hook_offset = stirrup_dia * 1.5
    first_tie_x = xs[1] if len(xs) > 2 else xs[0]
    
    if tie_mode in ["ALTERNATE", "EVERY_BAR"]:
        for i in range(1, len(xs) - 1, stride_x):
            ax.plot([xs[i], xs[i]], [tie_iy, tie_iy + tie_ih], 
                    color='#d95f02', linestyle='-', linewidth=1.6, zorder=3)
            ax.plot([xs[i], xs[i] - hook_offset], [tie_iy + tie_ih, tie_iy + tie_ih - hook_offset],
                    color='#d95f02', linewidth=1.6, zorder=3)
            ax.plot([xs[i], xs[i] + hook_offset], [tie_iy, tie_iy + hook_offset],
                    color='#d95f02', linewidth=1.6, zorder=3)

        for j in range(1, len(ys) - 1, stride_y):
            ax.plot([tie_ix, tie_ix + tie_iw], [ys[j], ys[j]], 
                    color='#d95f02', linestyle='-', linewidth=1.6, zorder=3)
            ax.plot([tie_ix + tie_iw, tie_ix + tie_iw - hook_offset], [ys[j], ys[j] - hook_offset],
                    color='#d95f02', linewidth=1.6, zorder=3)
            ax.plot([tie_ix, tie_ix + hook_offset], [ys[j], ys[j] + hook_offset],
                    color='#d95f02', linewidth=1.6, zorder=3)

    # Rebar Stations
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
    sample_bar_pos = None

    for x, y, pos in stations:
        if not use_Bundle:
            circle = patches.Circle((x, y), r, facecolor='#d62728', edgecolor='black', linewidth=1, zorder=4)
            ax.add_patch(circle)
            if sample_bar_pos is None and pos == 'bottom' and x >= B * 0.45:
                sample_bar_pos = (x, y)
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
                
            ax.add_patch(patches.Circle(c1, r, facecolor='#d62728', edgecolor='black', linewidth=1, zorder=4))
            ax.add_patch(patches.Circle(c2, r, facecolor='#d62728', edgecolor='black', linewidth=1, zorder=4))
            if sample_bar_pos is None and pos == 'bottom' and x >= B * 0.45:
                sample_bar_pos = c1

    if sample_bar_pos is None:
        sample_bar_pos = (x_min, y_min)

    # --- CLEAR CALLOUT ANNOTATIONS OUTSIDE DRAWING BOUNDARIES ---

    # 1. Longitudinal Bar Tag Callout (Anchored centered below the section)
    bar_desc = f"{active_layout['total_bars']}-T{dia} ({active_layout['Nx']}-T{dia} @ {cc_x:.0f}mm c/c B-face, {active_layout['Ny']}-T{dia} @ {cc_y:.0f}mm c/c D-face)"
    if use_Bundle:
        bar_desc = f"Bundled: {bar_desc}"

    ax.annotate(
        bar_desc,
        xy=sample_bar_pos,
        xytext=(B / 2.0, -D * 0.22),
        ha='center',
        va='top',
        arrowprops=dict(
            facecolor='#d62728', edgecolor='#d62728',
            arrowstyle='->', lw=1.5,
            connectionstyle="angle,angleA=0,angleB=90,rad=5"
        ),
        fontsize=9.0,
        fontweight='bold',
        color='#b30000',
        bbox=dict(boxstyle='round,pad=0.45', facecolor='#fff0f0', edgecolor='#d62728', lw=1.2)
    )

    # 2. Master Outer Tie Tag Callout (Anchored strictly to the left exterior)
    outer_tie_desc = f"Outer Tie:\nT{stirrup_dia} @ {s_vert_practical}mm c/c"
    ax.annotate(
        outer_tie_desc,
        xy=(tie_ox, tie_oy + tie_oh * 0.75),
        xytext=(-B * 0.20, tie_oy + tie_oh * 0.78),
        ha='right',
        va='center',
        arrowprops=dict(
            facecolor='#00529B', edgecolor='#00529B',
            arrowstyle='->', lw=1.5,
            connectionstyle="arc3,rad=0.1"
        ),
        fontsize=9.0,
        fontweight='bold',
        color='#003366',
        bbox=dict(boxstyle='round,pad=0.45', facecolor='#f0f6ff', edgecolor='#00529B', lw=1.2)
    )

    # 3. Internal Crosstie Tag Callout (Anchored below the outer tie tag on the left exterior)
    if tie_mode in ["ALTERNATE", "EVERY_BAR"]:
        tie_rule_label = "Every Bar Tied" if tie_mode == "EVERY_BAR" else "Alternate Bars Tied"
        inner_tie_desc = f"Crossties:\nT{stirrup_dia} @ {s_vert_practical}mm c/c\n({tie_rule_label})"
        ax.annotate(
            inner_tie_desc,
            xy=(first_tie_x, tie_iy + tie_ih * 0.45),
            xytext=(-B * 0.20, tie_iy + tie_ih * 0.35),
            ha='right',
            va='center',
            arrowprops=dict(
                facecolor='#d95f02', edgecolor='#d95f02',
                arrowstyle='->', lw=1.5,
                connectionstyle="arc3,rad=-0.1"
            ),
            fontsize=9.0,
            fontweight='bold',
            color='#993d00',
            bbox=dict(boxstyle='round,pad=0.45', facecolor='#fff5eb', edgecolor='#d95f02', lw=1.2)
        )

    # 4. Dimension Lines for Column Width B & Depth D
    # Width B Dimension (Top)
    dim_y = D + D * 0.06
    ax.annotate('', xy=(0, dim_y), xytext=(B, dim_y),
                arrowprops=dict(arrowstyle='<->', color='#222222', lw=1.3))
    ax.text(B / 2.0, dim_y + D * 0.02, f"B = {B} mm", ha='center', va='bottom', fontsize=9.5, fontweight='bold')

    # Depth D Dimension (Right)
    dim_x = B + B * 0.06
    ax.annotate('', xy=(dim_x, 0), xytext=(dim_x, D),
                arrowprops=dict(arrowstyle='<->', color='#222222', lw=1.3))
    ax.text(dim_x + B * 0.025, D / 2.0, f"D = {D} mm", ha='left', va='center', rotation=-90, fontsize=9.5, fontweight='bold')

    # Set canvas boundaries with ample margins so callouts never overlap the column geometry
    ax.set_xlim(-B * 0.65, B + B * 0.25)
    ax.set_ylim(-D * 0.32, D + D * 0.16)
    ax.set_aspect('equal')
    ax.axis('off')
    st.pyplot(fig)

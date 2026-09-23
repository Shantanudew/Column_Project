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
stirrup_dia = st.sidebar.selectbox("Stirrup Diameter (mm)", [8, 10, 12], index=1)
cover = st.sidebar.number_input("Clear Cover (mm)", value=40, step=5)

st.sidebar.header("Bar Selection Mode")
mode = st.sidebar.radio("Optimization Mode", ["Auto-Select Best Bar & Layout", "Manual Bar Selection"])

available_dias = [16, 20, 25, 32]
if mode == "Manual Bar Selection":
    dia_choice = st.sidebar.selectbox("Select Bar Diameter (mm)", available_dias, index=2)
    candidate_dias = [dia_choice]
else:
    candidate_dias = available_dias

target_min_s = 55.0
target_max_s = 75.0

# --- STRUCTURAL DEMAND ---
Ag = B * D
Ast_req = (p * Ag) / 100.0

# --- CORE SOLVER FUNCTION ---
def solve_layout(dia, bundled=False):
    a_bar = (np.pi * (dia ** 2)) / 4.0
    n_bars_needed = int(np.ceil(Ast_req / a_bar))
    if n_bars_needed < 4:
        n_bars_needed = 4
        
    # If bundled, each layout station holds 2 bars
    if bundled:
        n_stations_needed = int(np.ceil(n_bars_needed / 2.0))
        if n_stations_needed < 4:
            n_stations_needed = 4
    else:
        n_stations_needed = n_bars_needed

    span_x = B - 2 * (cover + stirrup_dia) - dia
    span_y = D - 2 * (cover + stirrup_dia) - dia
    
    max_search = max(15, int(np.ceil(n_stations_needed / 2)) + 4)
    best = None
    min_penalty = float("inf")
    
    for Nx in range(2, max_search):
        for Ny in range(2, max_search):
            stations = 2 * Nx + 2 * Ny - 4
            if stations >= n_stations_needed:
                if bundled:
                    # Clear gap accounts for two bar widths at each station
                    sx = (span_x - (Nx - 1) * (2 * dia)) / (Nx - 1)
                    sy = (span_y - (Ny - 1) * (2 * dia)) / (Ny - 1)
                else:
                    sx = (span_x - (Nx - 1) * dia) / (Nx - 1)
                    sy = (span_y - (Ny - 1) * dia) / (Ny - 1)
                
                if sx <= 0 or sy <= 0:
                    continue

                total_actual_bars = stations * (2 if bundled else 1)
                
                spacing_mid = (target_min_s + target_max_s) / 2.0
                penalty = abs(sx - spacing_mid) + abs(sy - spacing_mid) + (total_actual_bars - n_bars_needed) * 3
                
                if target_min_s <= sx <= target_max_s and target_min_s <= sy <= target_max_s:
                    penalty -= 40.0
                elif sx < target_min_s or sy < target_min_s:
                    penalty += 100.0
                
                if penalty < min_penalty:
                    min_penalty = penalty
                    best = {
                        "dia": dia,
                        "bundled": bundled,
                        "Nx": Nx,
                        "Ny": Ny,
                        "stations": stations,
                        "total_bars": total_actual_bars,
                        "Ast_provided": total_actual_bars * a_bar,
                        "sx": sx,
                        "sy": sy,
                        "penalty": penalty
                    }
    return best

# --- RUN ENGINE: SINGLE BARS FIRST, BUNDLES ONLY IF NECESSARY ---
evaluation_pool = []

# 1. Try single bars across allowed diameters
for d in candidate_dias:
    res = solve_layout(d, bundled=False)
    if res and res["sx"] >= 40.0 and res["sy"] >= 40.0:
        evaluation_pool.append(res)

# 2. Fallback to bundled bars if single bars do not clear minimum spacing
if not evaluation_pool:
    for d in candidate_dias:
        res = solve_layout(d, bundled=True)
        if res:
            evaluation_pool.append(res)

# Pick best layout by lowest penalty
best_layout = min(evaluation_pool, key=lambda x: x["penalty"])

use_Bundle = best_layout["bundled"]
dia = best_layout["dia"]

# --- TIE & CROSSTIE REQUIREMENTS (ACI 318-19 SECTION 25.7.2.3) ---
aci_threshold = 150.0  # 6-inch limit
station_width = (2 * dia) if use_Bundle else dia

# Clear distance across an untied (skipped) intermediate station
s_skip_x = 2 * best_layout["sx"] + station_width
s_skip_y = 2 * best_layout["sy"] + station_width

# Check if intermediate ties are needed and determine stride
has_intermediates = (best_layout["Nx"] > 2 or best_layout["Ny"] > 2)

if not has_intermediates:
    tie_mode = "NONE"
    stride_x = 0
    stride_y = 0
    tie_advice = "Outer Master Tie alone is sufficient (4 corner bars only)."
elif best_layout["sx"] > aci_threshold or best_layout["sy"] > aci_threshold:
    tie_mode = "EVERY_BAR"
    stride_x = 1
    stride_y = 1
    tie_advice = "EVERY intermediate bar requires a crosstie leg (adjacent clear spacing > 150 mm)."
elif s_skip_x > aci_threshold or s_skip_y > aci_threshold:
    tie_mode = "EVERY_BAR"
    stride_x = 1
    stride_y = 1
    tie_advice = "EVERY intermediate bar requires a crosstie leg (clear distance across skipped bar > 150 mm)."
else:
    tie_mode = "ALTERNATE"
    stride_x = 2
    stride_y = 2
    tie_advice = "Alternate bars tied with crossties (clear distance across skipped bar is <= 150 mm)."

# --- DASHBOARD OUTPUT ---
col1, col2 = st.columns([1.1, 1.2])

with col1:
    st.subheader("Design Decision Summary")
    st.markdown(f"**Required Area ($A_{{st}}$):** `{Ast_req:.1f} mm²`")
    st.markdown(f"**Provided Area:** `{best_layout['Ast_provided']:.1f} mm²` ({best_layout['total_bars']} bars of **#{dia} mm**)")
    st.markdown(f"**Arrangement Type:** `{'2-Bar Bundles' if use_Bundle else 'Single Regular Bars'}`")
    st.markdown(f"**Grid Stations:** `{best_layout['Nx']} along B × {best_layout['Ny']} along D`")
    
    st.divider()
    st.subheader("Clear Spacing Status")
    st.write(f"Clear Gap along Width ($B$): **{best_layout['sx']:.1f} mm**")
    st.write(f"Clear Gap along Depth ($D$): **{best_layout['sy']:.1f} mm**")
    
    if target_min_s <= best_layout['sx'] <= target_max_s and target_min_s <= best_layout['sy'] <= target_max_s:
        st.success("Target spacing achieved (55–75 mm). Optimum constructibility.")
    elif best_layout['sx'] >= target_min_s and best_layout['sy'] >= target_min_s:
        st.info("Spacing is clear and open (constructible).")
    else:
        st.error("Clear spacing tight (< 55 mm).")

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

# --- CROSS-SECTION PLOT ---
with col2:
    st.subheader("Section Cross-Section")
    fig, ax = plt.subplots(figsize=(7.5, 7.5))
    
    # Concrete Rectangle
    concrete = patches.Rectangle((0, 0), B, D, linewidth=2, edgecolor='black', facecolor='#fbfbfb')
    ax.add_patch(concrete)
    
    # Master Tie (Outer and Inner thickness lines)
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
    
    # Rebar Grid Generation
    r = dia / 2.0
    x_min = tie_inner_x + r
    x_max = tie_inner_x + tie_inner_w - r
    y_min = tie_inner_y + r
    y_max = tie_inner_y + tie_inner_h - r
    
    xs = np.linspace(x_min, x_max, best_layout["Nx"])
    ys = np.linspace(y_min, y_max, best_layout["Ny"])
    
    # Draw Internal Crossties based on ACI 150 mm spacing stride
    if tie_mode in ["ALTERNATE", "EVERY_BAR"]:
        # Vertical crossties linking Top and Bottom faces
        for i in range(1, len(xs) - 1, stride_x):
            ax.plot([xs[i], xs[i]], [y_min - r, y_max + r], 
                    color='#ff7f0e', linestyle='--', linewidth=1.3, zorder=2)
        # Horizontal crossties linking Left and Right faces
        for j in range(1, len(ys) - 1, stride_y):
            ax.plot([x_min - r, x_max + r], [ys[j], ys[j]], 
                    color='#ff7f0e', linestyle='--', linewidth=1.3, zorder=2)

    # Position collection
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
            # 45-degree inward bundles for corners
            if pos == 'corner_bl':
                c1, c2 = (x, y), (x + diag_shift, y + diag_shift)
            elif pos == 'corner_br':
                c1, c2 = (x, y), (x - diag_shift, y + diag_shift)
            elif pos == 'corner_tl':
                c1, c2 = (x, y), (x + diag_shift, y - diag_shift)
            elif pos == 'corner_tr':
                c1, c2 = (x, y), (x - diag_shift, y - diag_shift)
            # Parallel-to-face bundles for perimeters
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

"""
PyWake Uncertainty Propagation and Sobol Sensitivity Analysis

This script:
1. Sets up a wind farm simulation using PyWake
2. Defines realistic uncertainties in input parameters
3. Performs Sobol sensitivity analysis to quantify the impact of uncertainties
4. Generates flow field images showing sensitivity at different conditions
5. Saves results for further analysis
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import xarray as xr
from tqdm import tqdm
import os
from datetime import datetime
import pandas as pd

# For Sobol sensitivity analysis
from SALib.sample import saltelli
from SALib.analyze import sobol

# Import PyWake components
try:
    import py_wake
except ModuleNotFoundError:
    # Install PyWake if needed
    import sys
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", 
                          "git+https://gitlab.windenergy.dtu.dk/TOPFARM/PyWake.git"])
    import py_wake

from py_wake.examples.data.hornsrev1 import Hornsrev1Site, V80
from py_wake.literature.gaussian_models import Bastankhah_PorteAgel_2014
from py_wake import HorizontalGrid
from py_wake.flow_map import XYGrid

# Create output directory for results
results_dir = "pywake_uncertainty_results"
os.makedirs(results_dir, exist_ok=True)
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
run_dir = os.path.join(results_dir, f"run_{timestamp}")
os.makedirs(run_dir, exist_ok=True)

# Log file to capture the simulation details
log_file = os.path.join(run_dir, "simulation_log.txt")
with open(log_file, "w") as f:
    f.write(f"PyWake Uncertainty Propagation - Started at {datetime.now()}\n\n")

# Define baseline setup for wind farm
site = Hornsrev1Site()
x, y = site.initial_position.T
windTurbines = V80()

# Define the baseline wake model
k_default = 0.0324555  # Baseline wake decay constant
wf_model_baseline = Bastankhah_PorteAgel_2014(site, windTurbines, k=k_default)

# Log the baseline configuration
with open(log_file, "a") as f:
    f.write(f"Baseline configuration:\n")
    f.write(f"Wake model: Bastankhah_PorteAgel_2014\n")
    f.write(f"Wake decay constant (k): {k_default}\n")
    f.write(f"Number of turbines: {len(x)}\n\n")

# Define realistic uncertainty ranges for input parameters
# These will be used for Sobol sensitivity analysis
problem = {
    'num_vars': 4,
    'names': ['wind_speed', 'wind_direction', 'turbulence_intensity', 'wake_decay'],
    'bounds': [
        [6, 12],              # Wind speed (m/s): typical measurement uncertainty +/- 3 m/s
        [260, 280],           # Wind direction (degrees): typical uncertainty +/- 10 degrees
        [0.05, 0.15],         # Turbulence intensity: typical range with uncertainty
        [0.025, 0.04]         # Wake decay constant: uncertainty range around baseline
    ]
}

# Log the uncertainty ranges
with open(log_file, "a") as f:
    f.write("Uncertainty ranges for input parameters:\n")
    for i, name in enumerate(problem['names']):
        f.write(f"{name}: [{problem['bounds'][i][0]}, {problem['bounds'][i][1]}]\n")
    f.write("\n")

# Generate samples for Sobol analysis
# N defines the sample size - larger values give more accurate results but take longer
N = 128  # Number of samples (adjust as needed for computational requirements)
param_values = saltelli.sample(problem, N, calc_second_order=False)

# Log the sampling details
with open(log_file, "a") as f:
    f.write(f"Sobol sensitivity analysis:\n")
    f.write(f"Number of base samples (N): {N}\n")
    f.write(f"Total number of model evaluations: {len(param_values)}\n\n")

# Define flow map grid for analysis
# We'll use a horizontal grid around the wind farm
grid_resolution = 100  # Balance between detail and computational time
extend_factor = 0.5    # How far to extend the grid beyond turbine locations
x_min, x_max = min(x) - extend_factor * (max(x) - min(x)), max(x) + extend_factor * (max(x) - min(x))
y_min, y_max = min(y) - extend_factor * (max(y) - min(y)), max(y) + extend_factor * (max(y) - min(y))

# Create grid for flow map
grid = HorizontalGrid(
    x=np.linspace(x_min, x_max, grid_resolution),
    y=np.linspace(y_min, y_max, grid_resolution),
    h=windTurbines.hub_height(0)  # Use turbine hub height
)

with open(log_file, "a") as f:
    f.write(f"Flow map grid configuration:\n")
    f.write(f"Resolution: {grid_resolution}x{grid_resolution} points\n")
    f.write(f"X range: [{x_min:.1f}, {x_max:.1f}] m\n")
    f.write(f"Y range: [{y_min:.1f}, {y_max:.1f}] m\n")
    f.write(f"Height: {windTurbines.hub_height(0)} m (hub height)\n\n")

# Storage for flow map results at each sample point
ws_eff_results = []

# Progress tracking
print(f"Running {len(param_values)} simulations for Sobol analysis...")

# Run simulations for each parameter set
for i, params in enumerate(tqdm(param_values)):
    # Extract parameters from sample
    ws, wd, ti, k = params
    
    # Update the model with new wake decay constant
    wf_model = Bastankhah_PorteAgel_2014(site, windTurbines, k=k)
    
    # Run simulation with specific wind conditions
    sim_res = wf_model(x, y, wd=wd, ws=ws, TI=ti)
    
    # Generate flow map for this parameter set
    flow_map = sim_res.flow_map(grid=grid, wd=wd, ws=ws)
    
    # Store the effective wind speed field
    ws_eff_results.append(flow_map.WS_eff.values)
    
    # Every 10 samples, save an intermediate flow map to visualize
    if i % 10 == 0 or i == len(param_values) - 1:
        plt.figure(figsize=(10, 8))
        
        # Create a custom colormap that's more friendly for those with color vision deficiencies
        colors = plt.cm.viridis(np.linspace(0, 1, 256))
        custom_cmap = LinearSegmentedColormap.from_list('custom_cmap', colors)
        
        # Plot the flow map
        im = plt.contourf(flow_map.x, flow_map.y, flow_map.WS_eff, 
                          levels=50, cmap=custom_cmap)
        plt.colorbar(im, label='WS_eff (m/s)')
        
        # Add turbine positions
        plt.scatter(x, y, color='red', s=20, label='Turbines')
        
        # Add parameter information
        plt.title(f"Flow map - Sample {i}\nWS={ws:.2f} m/s, WD={wd:.1f}°, TI={ti:.3f}, k={k:.4f}")
        plt.xlabel('x [m]')
        plt.ylabel('y [m]')
        plt.grid(alpha=0.3)
        plt.axis('equal')
        
        # Save the figure
        plt.savefig(os.path.join(run_dir, f"flow_map_sample_{i:03d}.png"), dpi=150, bbox_inches='tight')
        plt.close()

# Convert results to numpy array for analysis
ws_eff_array = np.array(ws_eff_results)

# Flatten the spatial dimensions to analyze sensitivity at each grid point
original_shape = ws_eff_array.shape[1:]  # Remember original shape for reshaping results
Y_flat = ws_eff_array.reshape(len(param_values), -1)

# Storage for sensitivity indices at each grid point
S1_indices = np.zeros((len(problem['names']), *original_shape))

print("Computing Sobol sensitivity indices...")

# Analyze Sobol sensitivity for each grid point
# This can be computationally intensive for large grids
for j in tqdm(range(Y_flat.shape[1])):
    # Extract model outputs for this grid point
    Y_j = Y_flat[:, j]
    
    # If there's no variation at this point, skip it
    if np.all(Y_j == Y_j[0]):
        continue
    
    # Run Sobol analysis
    Si = sobol.analyze(problem, Y_j, calc_second_order=False, print_to_console=False)
    
    # Store first-order sensitivity indices for each parameter
    for k, name in enumerate(problem['names']):
        S1_indices[k, np.unravel_index(j, original_shape)] = Si['S1'][k]

# Reshape sensitivity indices back to original grid shape
S1_reshaped = [S1_indices[i].reshape(original_shape) for i in range(len(problem['names']))]

# Save the sensitivity indices
sensitivity_file = os.path.join(run_dir, "sobol_sensitivity_indices.npz")
np.savez(sensitivity_file, 
         S1_wind_speed=S1_reshaped[0],
         S1_wind_direction=S1_reshaped[1],
         S1_turbulence_intensity=S1_reshaped[2],
         S1_wake_decay=S1_reshaped[3],
         x_grid=flow_map.x,
         y_grid=flow_map.y,
         param_names=problem['names'])

print(f"Saved sensitivity indices to {sensitivity_file}")

# Create a figure with subplots for each parameter's sensitivity
plt.figure(figsize=(15, 12))

# Define a colormap
cmap = plt.cm.viridis

for i, name in enumerate(problem['names']):
    plt.subplot(2, 2, i+1)
    
    # Plot the sensitivity map for this parameter
    im = plt.contourf(flow_map.x, flow_map.y, S1_reshaped[i], 
                      levels=20, cmap=cmap, vmin=0, vmax=1)
    
    # Add colorbar
    cbar = plt.colorbar(im)
    cbar.set_label(f'Sensitivity Index (S1) for {name}')
    
    # Add turbine positions
    plt.scatter(x, y, color='red', s=10, label='Turbines')
    
    plt.title(f'Sobol Sensitivity - {name}')
    plt.xlabel('x [m]')
    plt.ylabel('y [m]')
    plt.grid(alpha=0.3)
    plt.axis('equal')

plt.tight_layout()
plt.savefig(os.path.join(run_dir, "sobol_sensitivity_maps.png"), dpi=200, bbox_inches='tight')
plt.close()

# Create individual high-quality sensitivity maps for each parameter
for i, name in enumerate(problem['names']):
    plt.figure(figsize=(10, 8))
    
    # Plot the sensitivity map with a more detailed colorbar
    im = plt.contourf(flow_map.x, flow_map.y, S1_reshaped[i], 
                     levels=50, cmap=cmap, vmin=0, vmax=1)
    
    # Add an informative colorbar
    cbar = plt.colorbar(im)
    cbar.set_label(f'Sobol First-Order Sensitivity Index (S1)')
    
    # Add turbine positions
    plt.scatter(x, y, color='red', s=20, label='Turbines')
    
    # Add wind direction arrow for reference (using the mean of the sampled wind directions)
    mean_wd = np.mean(param_values[:, 1])
    arrow_length = (max(x) - min(x)) * 0.1
    arrow_x = min(x) - arrow_length * 0.5
    arrow_y = min(y) - arrow_length * 0.5
    plt.arrow(arrow_x, arrow_y, 
             arrow_length * np.cos(np.radians(270 - mean_wd)), 
             arrow_length * np.sin(np.radians(270 - mean_wd)),
             head_width=arrow_length*0.2, head_length=arrow_length*0.3, 
             fc='blue', ec='blue')
    plt.text(arrow_x, arrow_y - arrow_length*0.4, 
             f"Mean Wind\nDirection: {mean_wd:.1f}°", 
             ha='center', va='top', color='blue')
    
    plt.title(f'Sensitivity of WS_eff to {name.replace("_", " ").title()}')
    plt.xlabel('x [m]')
    plt.ylabel('y [m]')
    plt.grid(alpha=0.3)
    plt.axis('equal')
    
    # Save the high-quality figure
    plt.savefig(os.path.join(run_dir, f"sensitivity_{name}.png"), dpi=300, bbox_inches='tight')
    plt.close()

# Create one final combined map showing the parameter with the highest sensitivity at each point
dominant_parameter = np.argmax(S1_indices, axis=0)

# Create a custom colormap for the dominant parameters
colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728']  # Blue, orange, green, red
custom_cmap = LinearSegmentedColormap.from_list('custom_cmap', colors, N=4)

plt.figure(figsize=(12, 10))
im = plt.imshow(dominant_parameter, extent=[min(flow_map.x), max(flow_map.x), 
                                          min(flow_map.y), max(flow_map.y)],
               origin='lower', cmap=custom_cmap, vmin=-0.5, vmax=3.5)

# Add turbine positions
plt.scatter(x, y, color='black', s=20, edgecolor='white')

# Create a custom legend for the parameters
from matplotlib.patches import Patch
legend_elements = [Patch(facecolor=colors[i], label=name.replace('_', ' ').title())
                  for i, name in enumerate(problem['names'])]
plt.legend(handles=legend_elements, loc='upper right', title='Dominant Parameter')

plt.title('Dominant Sensitivity Parameter for WS_eff')
plt.xlabel('x [m]')
plt.ylabel('y [m]')
plt.grid(alpha=0.3)
plt.axis('equal')

# Save the dominant sensitivity map
plt.savefig(os.path.join(run_dir, "dominant_sensitivity_parameter.png"), dpi=300, bbox_inches='tight')
plt.close()

# Create a summary report
with open(os.path.join(run_dir, "summary_report.txt"), "w") as f:
    f.write("PyWake Uncertainty Propagation - Summary Report\n")
    f.write(f"Generated on: {datetime.now()}\n\n")
    
    f.write("Simulation Configuration:\n")
    f.write(f"- Wake model: Bastankhah_PorteAgel_2014\n")
    f.write(f"- Base wake decay constant (k): {k_default}\n")
    f.write(f"- Number of turbines: {len(x)}\n")
    f.write(f"- Grid resolution: {grid_resolution}x{grid_resolution}\n\n")
    
    f.write("Uncertainty Parameters:\n")
    for i, name in enumerate(problem['names']):
        f.write(f"- {name}: [{problem['bounds'][i][0]}, {problem['bounds'][i][1]}]\n")
    f.write("\n")
    
    f.write("Sobol Analysis:\n")
    f.write(f"- Base sample size (N): {N}\n")
    f.write(f"- Total model evaluations: {len(param_values)}\n\n")
    
    f.write("Key Findings:\n")
    # Calculate average sensitivity across the domain for each parameter
    avg_sensitivity = [np.mean(S1_reshaped[i]) for i in range(len(problem['names']))]
    for i, name in enumerate(problem['names']):
        f.write(f"- {name}: Average sensitivity = {avg_sensitivity[i]:.4f}\n")
    
    # Identify most sensitive parameter on average
    most_sensitive = problem['names'][np.argmax(avg_sensitivity)]
    f.write(f"\nThe parameter with the highest average sensitivity across the domain is: {most_sensitive}\n")
    
    # Calculate dominant parameter coverage
    unique, counts = np.unique(dominant_parameter, return_counts=True)
    total_cells = dominant_parameter.size
    f.write("\nDominant parameter distribution across the domain:\n")
    for i in range(len(problem['names'])):
        if i in unique:
            idx = np.where(unique == i)[0][0]
            percentage = (counts[idx] / total_cells) * 100
            f.write(f"- {problem['names'][i]}: {percentage:.1f}% of domain\n")
        else:
            f.write(f"- {problem['names'][i]}: 0.0% of domain\n")

print(f"Analysis complete! Results saved to: {run_dir}")

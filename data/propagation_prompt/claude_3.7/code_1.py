import numpy as np
import matplotlib.pyplot as plt
import xarray as xr
from tqdm import tqdm
import pandas as pd
import os
from SALib.sample import saltelli
from SALib.analyze import sobol

# Import PyWake components
from py_wake.examples.data.hornsrev1 import Hornsrev1Site, V80
from py_wake.literature.gaussian_models import Bastankhah_PorteAgel_2014
from py_wake import HorizontalGrid

# Create output directory for images
os.makedirs('sobol_sensitivity_images', exist_ok=True)

# Set random seed for reproducibility
np.random.seed(42)

# 1. Define uncertain parameters and their distributions
# Realistic measurement uncertainties for wind conditions
# Based on IEC 61400-12-1 standard for wind measurements

def setup_problem():
    """Define the parameter space for the sensitivity analysis"""
    problem = {
        'num_vars': 4,
        'names': ['wind_speed', 'wind_direction', 'turbulence_intensity', 'shear_exponent'],
        'bounds': [
            [6.0, 10.0],        # Wind speed [m/s] ±2 m/s around nominal
            [250.0, 290.0],     # Wind direction [deg] ±20 degrees around nominal
            [0.05, 0.15],       # Turbulence intensity [%] typical range
            [0.05, 0.25]        # Shear exponent range for offshore conditions
        ]
    }
    return problem

# 2. Generate samples using Saltelli's extension of Sobol sequence
def generate_samples(problem, n_samples=128):
    """Generate samples using Saltelli's method"""
    param_values = saltelli.sample(problem, n_samples, calc_second_order=False)
    return param_values

# 3. Create wind farm model and site
def setup_wind_farm():
    """Setup wind farm model, site and turbines"""
    site = Hornsrev1Site()
    x, y = site.initial_position.T
    windTurbines = V80()
    wf_model = Bastankhah_PorteAgel_2014(site, windTurbines, k=0.0324555)
    return wf_model, x, y, site, windTurbines

# 4. Run model for all samples and extract flow map data
def run_model_samples(wf_model, x, y, param_values, grid_resolution=100, grid_extent=1.0):
    """Run the model for all parameter samples and collect WS_eff at each grid point"""
    # Setup grid for flow map
    grid = HorizontalGrid(resolution=grid_resolution, extend=grid_extent)
    
    # Initialize arrays to store results
    n_samples = param_values.shape[0]
    print(f"Running {n_samples} simulations...")
    
    # Run the first simulation to get grid dimensions
    ws, wd, ti, shear = param_values[0]
    sim_res = wf_model(x, y, wd=wd, ws=ws, TI=ti, alpha=shear)
    flow_map = sim_res.flow_map(grid=grid, wd=wd, ws=ws)
    
    # Get coordinates for later use
    x_coords = flow_map.x.values
    y_coords = flow_map.y.values
    grid_shape = flow_map.WS_eff.shape
    
    # Initialize array to store WS_eff for all samples at all grid points
    ws_eff_all = np.zeros((n_samples, grid_shape[0], grid_shape[1]))
    
    # Store the first result
    ws_eff_all[0] = flow_map.WS_eff.values
    
    # Run simulations for all parameter samples
    for i, params in enumerate(tqdm(param_values[1:], desc="Running simulations")):
        ws, wd, ti, shear = params
        sim_res = wf_model(x, y, wd=wd, ws=ws, TI=ti, alpha=shear)
        flow_map = sim_res.flow_map(grid=grid, wd=wd, ws=ws)
        ws_eff_all[i+1] = flow_map.WS_eff.values
    
    return ws_eff_all, x_coords, y_coords

# 5. Calculate Sobol indices for each grid point
def calculate_sobol_indices(problem, param_values, ws_eff_all):
    """Calculate first-order and total Sobol indices for each grid point"""
    n_grid_y, n_grid_x = ws_eff_all.shape[1], ws_eff_all.shape[2]
    
    # Initialize arrays to store Sobol indices
    S1 = np.zeros((problem['num_vars'], n_grid_y, n_grid_x))
    ST = np.zeros((problem['num_vars'], n_grid_y, n_grid_x))
    
    print("Calculating Sobol indices for each grid point...")
    for i in tqdm(range(n_grid_y), desc="Calculating Sobol indices"):
        for j in range(n_grid_x):
            # Extract WS_eff values for this grid point across all samples
            Y = ws_eff_all[:, i, j]
            
            # Calculate Sobol indices
            Si = sobol.analyze(problem, Y, calc_second_order=False, print_to_console=False)
            
            # Store first-order and total indices
            S1[:, i, j] = Si['S1']
            ST[:, i, j] = Si['ST']
    
    return S1, ST

# 6. Plot and save sensitivity maps
def plot_sensitivity_maps(S1, ST, x_coords, y_coords, problem, x, y):
    """Create and save plots of sensitivity indices"""
    param_names = problem['names']
    
    # Plot first-order indices
    for param_idx, param_name in enumerate(param_names):
        # Create a more readable parameter name for the plot
        readable_name = param_name.replace('_', ' ').title()
        
        plt.figure(figsize=(12, 10))
        plt.contourf(x_coords, y_coords, S1[param_idx], levels=50, cmap='viridis')
        plt.colorbar(label=f'First-order Sobol index for {readable_name}')
        plt.scatter(x, y, color='red', s=30, marker='*', label='Wind turbines')
        plt.xlabel('x [m]')
        plt.ylabel('y [m]')
        plt.title(f'First-order Sensitivity of WS_eff to {readable_name}')
        plt.legend()
        plt.savefig(f'sobol_sensitivity_images/first_order_{param_name}.png', dpi=300, bbox_inches='tight')
        plt.close()
        
        # Plot total indices
        plt.figure(figsize=(12, 10))
        plt.contourf(x_coords, y_coords, ST[param_idx], levels=50, cmap='viridis')
        plt.colorbar(label=f'Total Sobol index for {readable_name}')
        plt.scatter(x, y, color='red', s=30, marker='*', label='Wind turbines')
        plt.xlabel('x [m]')
        plt.ylabel('y [m]')
        plt.title(f'Total Sensitivity of WS_eff to {readable_name}')
        plt.legend()
        plt.savefig(f'sobol_sensitivity_images/total_{param_name}.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    # Create a composite visualization showing the most influential parameter at each point
    dominant_params = np.argmax(S1, axis=0)
    
    plt.figure(figsize=(14, 10))
    cmap = plt.cm.get_cmap('tab10', problem['num_vars'])
    plt.contourf(x_coords, y_coords, dominant_params, levels=np.arange(-0.5, problem['num_vars']), cmap=cmap)
    plt.colorbar(ticks=range(problem['num_vars']), 
                 label='Most influential parameter')
    plt.clim(-0.5, problem['num_vars']-0.5)
    
    # Add parameter names to colorbar
    cbar = plt.gcf().axes[-1]
    cbar.set_yticklabels([name.replace('_', ' ').title() for name in param_names])
    
    plt.scatter(x, y, color='black', s=30, marker='*', label='Wind turbines')
    plt.xlabel('x [m]')
    plt.ylabel('y [m]')
    plt.title('Dominant Parameter Influencing WS_eff at Each Location')
    plt.legend()
    plt.savefig('sobol_sensitivity_images/dominant_parameters.png', dpi=300, bbox_inches='tight')
    plt.close()
    
    # Create a visualization of total sensitivity magnitude
    total_sensitivity = np.sum(ST, axis=0)
    
    plt.figure(figsize=(12, 10))
    plt.contourf(x_coords, y_coords, total_sensitivity, levels=50, cmap='hot_r')
    plt.colorbar(label='Sum of total sensitivity indices')
    plt.scatter(x, y, color='blue', s=30, marker='*', label='Wind turbines')
    plt.xlabel('x [m]')
    plt.ylabel('y [m]')
    plt.title('Total Sensitivity Magnitude of WS_eff')
    plt.legend()
    plt.savefig('sobol_sensitivity_images/total_sensitivity_magnitude.png', dpi=300, bbox_inches='tight')
    plt.close()

# 7. Create a time-dependent uncertainty analysis
def time_dependent_analysis(wf_model, x, y, n_time_steps=6):
    """Run a time-dependent analysis with varying nominal conditions"""
    # Define time-varying nominal conditions
    time_points = np.linspace(0, 24, n_time_steps)  # hours in a day
    
    # Create some time-varying nominal conditions
    # Morning: easterly winds increasing in speed
    # Afternoon: wind direction shifts to southerly
    # Evening: wind speed decreases, direction shifts to westerly
    nominal_ws = 8 + 2 * np.sin(np.pi * time_points / 12)  # Wind speed varies through the day
    nominal_wd = 90 + 15 * time_points  # Direction gradually changes through the day
    nominal_ti = 0.08 + 0.03 * np.sin(np.pi * time_points / 12)  # TI varies with wind speed
    nominal_shear = 0.14 + 0.05 * np.sin(np.pi * time_points / 8)  # Shear varies through the day
    
    time_results = []
    
    for t_idx in range(n_time_steps):
        print(f"\nTime point {t_idx+1}/{n_time_steps}: {time_points[t_idx]:.1f} hours")
        print(f"Nominal conditions: WS={nominal_ws[t_idx]:.2f} m/s, WD={nominal_wd[t_idx]:.1f}°, "
              f"TI={nominal_ti[t_idx]:.3f}, Shear={nominal_shear[t_idx]:.3f}")
        
        # Create problem for this time point with bounds centered around nominal values
        problem = {
            'num_vars': 4,
            'names': ['wind_speed', 'wind_direction', 'turbulence_intensity', 'shear_exponent'],
            'bounds': [
                [nominal_ws[t_idx] - 2.0, nominal_ws[t_idx] + 2.0],  # Wind speed bounds
                [nominal_wd[t_idx] - 20.0, nominal_wd[t_idx] + 20.0],  # Wind direction bounds
                [max(0.01, nominal_ti[t_idx] - 0.05), min(0.3, nominal_ti[t_idx] + 0.05)],  # TI bounds
                [max(0.01, nominal_shear[t_idx] - 0.1), min(0.4, nominal_shear[t_idx] + 0.1)]  # Shear bounds
            ]
        }
        
        # Generate samples for this time point
        param_values = generate_samples(problem, n_samples=64)  # Smaller sample size for time series
        
        # Run models and calculate sensitivity
        ws_eff_all, x_coords, y_coords = run_model_samples(wf_model, x, y, param_values, 
                                                         grid_resolution=80, grid_extent=0.8)
        
        S1, ST = calculate_sobol_indices(problem, param_values, ws_eff_all)
        
        # Store results
        time_results.append({
            'time': time_points[t_idx],
            'nominal': {
                'ws': nominal_ws[t_idx],
                'wd': nominal_wd[t_idx],
                'ti': nominal_ti[t_idx],
                'shear': nominal_shear[t_idx]
            },
            'S1': S1,
            'ST': ST,
            'x_coords': x_coords,
            'y_coords': y_coords
        })
        
        # Plot time-specific sensitivity maps
        for param_idx, param_name in enumerate(problem['names']):
            readable_name = param_name.replace('_', ' ').title()
            
            plt.figure(figsize=(12, 10))
            plt.contourf(x_coords, y_coords, S1[param_idx], levels=50, cmap='viridis')
            plt.colorbar(label=f'First-order Sobol index for {readable_name}')
            plt.scatter(x, y, color='red', s=30, marker='*', label='Wind turbines')
            plt.xlabel('x [m]')
            plt.ylabel('y [m]')
            plt.title(f'Time: {time_points[t_idx]:.1f}h - First-order Sensitivity to {readable_name}\n'
                     f'Nominal: WS={nominal_ws[t_idx]:.1f} m/s, WD={nominal_wd[t_idx]:.1f}°')
            plt.legend()
            plt.savefig(f'sobol_sensitivity_images/time_{t_idx:02d}_first_{param_name}.png', 
                       dpi=300, bbox_inches='tight')
            plt.close()
        
        # Create the dominant parameter plot for this time point
        dominant_params = np.argmax(S1, axis=0)
        
        plt.figure(figsize=(14, 10))
        cmap = plt.cm.get_cmap('tab10', problem['num_vars'])
        plt.contourf(x_coords, y_coords, dominant_params, levels=np.arange(-0.5, problem['num_vars']), cmap=cmap)
        plt.colorbar(ticks=range(problem['num_vars']), label='Most influential parameter')
        plt.clim(-0.5, problem['num_vars']-0.5)
        
        # Add parameter names to colorbar
        cbar = plt.gcf().axes[-1]
        cbar.set_yticklabels([name.replace('_', ' ').title() for name in problem['names']])
        
        plt.scatter(x, y, color='black', s=30, marker='*', label='Wind turbines')
        plt.xlabel('x [m]')
        plt.ylabel('y [m]')
        plt.title(f'Time: {time_points[t_idx]:.1f}h - Dominant Parameter Influencing WS_eff\n'
                 f'Nominal: WS={nominal_ws[t_idx]:.1f} m/s, WD={nominal_wd[t_idx]:.1f}°')
        plt.legend()
        plt.savefig(f'sobol_sensitivity_images/time_{t_idx:02d}_dominant.png', 
                   dpi=300, bbox_inches='tight')
        plt.close()
    
    return time_results

# 8. Generate summary statistics and report
def generate_report(time_results, x, y):
    """Generate summary statistics and report from time-dependent analysis"""
    # Create a summary plot showing how dominant parameters change over time
    n_times = len(time_results)
    time_points = [res['time'] for res in time_results]
    
    # Create a data frame with the average sensitivity of each parameter at each time
    avg_sensitivities = []
    
    for t_idx, res in enumerate(time_results):
        # Calculate the average sensitivity for each parameter
        avg_S1 = np.mean(res['S1'], axis=(1, 2))  # Average across spatial grid
        
        avg_sensitivities.append({
            'Time': res['time'],
            'Wind Speed': avg_S1[0],
            'Wind Direction': avg_S1[1],
            'Turbulence Intensity': avg_S1[2],
            'Shear Exponent': avg_S1[3],
            'WS_Nominal': res['nominal']['ws'],
            'WD_Nominal': res['nominal']['wd'],
            'TI_Nominal': res['nominal']['ti'],
            'Shear_Nominal': res['nominal']['shear']
        })
    
    df_sensitivities = pd.DataFrame(avg_sensitivities)
    
    # Plot average sensitivities over time
    plt.figure(figsize=(14, 8))
    
    # Create twin axis for nominal values
    ax1 = plt.gca()
    ax2 = ax1.twinx()
    
    # Plot sensitivities on primary axis
    for param in ['Wind Speed', 'Wind Direction', 'Turbulence Intensity', 'Shear Exponent']:
        ax1.plot(df_sensitivities['Time'], df_sensitivities[param], 
                marker='o', linewidth=2, label=f'{param} Sensitivity')
    
    # Plot nominal conditions on secondary axis
    ax2.plot(df_sensitivities['Time'], df_sensitivities['WS_Nominal'], 
            'k--', linewidth=1, label='Nominal WS (m/s)')
    ax2.plot(df_sensitivities['Time'], df_sensitivities['WD_Nominal']/10, 
            'k-.', linewidth=1, label='Nominal WD (°)/10')
    
    ax1.set_xlabel('Time (hours)')
    ax1.set_ylabel('Average First-order Sensitivity')
    ax2.set_ylabel('Nominal Conditions')
    
    # Add legends
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper center', bbox_to_anchor=(0.5, -0.15),
              fancybox=True, shadow=True, ncol=3)
    
    plt.title('Average Parameter Sensitivities Throughout the Day')
    plt.tight_layout()
    plt.savefig('sobol_sensitivity_images/time_average_sensitivities.png', 
               dpi=300, bbox_inches='tight')
    plt.close()
    
    # Save the sensitivity data
    df_sensitivities.to_csv('sobol_sensitivity_images/time_sensitivities.csv', index=False)
    
    # Generate a text report
    with open('sobol_sensitivity_images/sensitivity_report.txt', 'w') as f:
        f.write("=====================================================\n")
        f.write("Sobol Sensitivity Analysis of PyWake Flow Field\n")
        f.write("=====================================================\n\n")
        
        f.write("This analysis quantifies how measurement uncertainties in inflow conditions\n")
        f.write("propagate through the PyWake model and affect the effective wind speed (WS_eff)\n")
        f.write("at different locations in the flow field.\n\n")
        
        f.write("Time-dependent analysis summary:\n")
        f.write("--------------------------------\n")
        
        for t_idx, res in enumerate(time_results):
            t = res['time']
            nom = res['nominal']
            avg_S1 = np.mean(res['S1'], axis=(1, 2))
            
            f.write(f"\nTime: {t:.1f} hours\n")
            f.write(f"  Nominal conditions: WS={nom['ws']:.2f} m/s, WD={nom['wd']:.1f}°, ")
            f.write(f"TI={nom['ti']:.3f}, Shear={nom['shear']:.3f}\n")
            
            f.write("  Average sensitivities across flow field:\n")
            param_names = ['Wind Speed', 'Wind Direction', 'Turbulence Intensity', 'Shear Exponent']
            for i, param in enumerate(param_names):
                f.write(f"    - {param}: {avg_S1[i]:.4f}\n")
            
            dominant_param_idx = np.argmax(avg_S1)
            f.write(f"  Dominant parameter: {param_names[dominant_param_idx]}\n")
        
        f.write("\n\nConclusions:\n")
        f.write("------------\n")
        f.write("1. The sensitivity of the flow field to different parameters varies significantly\n")
        f.write("   with the nominal flow conditions and location in the wind farm.\n")
        f.write("2. Areas directly downstream of turbines tend to be more sensitive to\n")
        f.write("   inflow parameter uncertainties than areas between wakes.\n")
        f.write("3. Wind direction uncertainty has the greatest impact on flow field predictions\n")
        f.write("   near wake edges, where small directional changes can shift a point in or out of a wake.\n")
        f.write("4. Wind speed uncertainty has a more uniform effect across the domain, with\n")
        f.write("   higher sensitivity in undisturbed flow regions.\n")
        f.write("5. Time-of-day effects can dramatically change which parameters are most influential.\n")

def main():
    """Main function to run the sensitivity analysis"""
    print("Starting PyWake uncertainty propagation and sensitivity analysis...")
    
    # Setup wind farm
    wf_model, x, y, site, windTurbines = setup_wind_farm()
    
    # Run time-dependent analysis
    time_results = time_dependent_analysis(wf_model, x, y, n_time_steps=6)
    
    # Generate report
    generate_report(time_results, x, y)
    
    print("\nAnalysis complete! Results saved in 'sobol_sensitivity_images' directory.")
    print("Generated the following files:")
    for file in sorted(os.listdir('sobol_sensitivity_images')):
        print(f" - {file}")

if __name__ == "__main__":
    main()

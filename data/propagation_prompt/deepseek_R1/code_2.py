# Install required packages if needed
try:
    import SALib
except ModuleNotFoundError:
    !pip install SALib

import numpy as np
import matplotlib.pyplot as plt
from SALib import Sample, Analyze
from py_wake.examples.data.hornsrev1 import Hornsrev1Site, V80
from py_wake.literature.gaussian_models import Bastankhah_PorteAgel_2014
from py_wake import HorizontalGrid

# 1. Define uncertain parameters and their bounds
problem = {
    'num_vars': 3,
    'names': ['ws', 'wd', 'TI'],
    'bounds': [
        [9.8 - 0.5, 9.8 + 0.5],    # Wind speed uncertainty ±0.5 m/s
        [270 - 5, 270 + 5],        # Wind direction uncertainty ±5 deg
        [0.1 - 0.05, 0.1 + 0.05]   # Turbulence intensity uncertainty ±0.05
    ]
}

# 2. Generate Sobol samples
n_samples = 100  # Reduced for demonstration; increase for accuracy
param_values = Sample.saltelli.sample(problem, n_samples, calc_second_order=False)

# 3. Initialize PyWake model
site = Hornsrev1Site()
x, y = site.initial_position.T
windTurbines = V80()
wf_model = Bastankhah_PorteAgel_2014(site, windTurbines, k=0.0324555)

# 4. Define grid for flow map
grid = HorizontalGrid(resolution=100, extend=500)

# 5. Run simulations and collect WS_eff data
outputs = []
for params in param_values:
    ws_perturbed, wd_perturbed, TI_perturbed = params
    
    # Run simulation with perturbed parameters
    sim_res = wf_model(
        x, y,
        wd=wd_perturbed,
        ws=ws_perturbed,
        TI=TI_perturbed
    )
    
    # Extract flow map
    flow_map = sim_res.flow_map(grid=grid)
    ws_eff = flow_map.WS_eff.squeeze().values  # Extract WS_eff grid
    
    outputs.append(ws_eff)

# 6. Perform Sobol sensitivity analysis
Si = Analyze.sobol.analyze(problem, np.array(outputs), print_to_console=False)

# 7. Plot Sobol indices for each parameter
fig, axes = plt.subplots(1, 3, figsize=(18, 6))
titles = ['Wind Speed (S1)', 'Wind Direction (S1)', 'Turbulence Intensity (S1)']

for i, ax in enumerate(axes):
    # Reshape sensitivity indices to grid shape
    sensitivity_grid = Si['S1'][:, i].reshape(grid.shape)
    
    # Plot flow map
    im = ax.imshow(sensitivity_grid, origin='lower', extent=flow_map.extent)
    plt.colorbar(im, ax=ax, label='Sobol Index')
    ax.set_xlabel('x [m]')
    ax.set_ylabel('y [m]')
    ax.set_title(titles[i])

plt.tight_layout()
plt.savefig('sobol_sensitivity_flowmaps.png')
plt.show()

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import xarray as xr
from py_wake.rotor_avg_models.gaussian_overlap_model import GaussianOverlapAvgModel
from py_wake.deficit_models.gaussian import TurboGaussianDeficit
from py_wake.examples.data.dtu10mw._dtu10mw import DTU10MW
from py_wake.deficit_models.gaussian import BlondelSuperGaussianDeficit2020
from py_wake import HorizontalGrid
from py_wake.deflection_models import JimenezWakeDeflection
from py_wake.turbulence_models import CrespoHernandez
from py_wake.rotor_avg_models import RotorCenter
from py_wake.deficit_models import SelfSimilarityDeficit2020
from py_wake.wind_farm_models import PropagateDownwind, All2AllIterative
from py_wake.superposition_models import LinearSum
from py_wake.ground_models import Mirror
from py_wake.examples.data.hornsrev1 import Hornsrev1Site
from bayes_opt import BayesianOptimization
from py_wake.deficit_models.utils import ct2a_mom1d


class WakeModelConfig:
    """Configuration class for wake modeling parameters and settings"""
    
    def __init__(self, model_type=2, downwind=True):
        """
        Initialize wake model configuration
        
        Parameters:
        -----------
        model_type : int
            Model type (1 or 2)
        downwind : bool
            If True, model downwind effects, otherwise model upwind effects
        """
        self.MODEL = model_type
        self.DOWNWIND = downwind
        
        if self.MODEL not in {1, 2}:
            raise ValueError("MODEL must be either 1 or 2")
            
        # Set region of interest boundaries based on downwind setting
        if self.DOWNWIND:
            self.X_LB = 2
            self.X_UB = 10
        else:
            self.X_LB = -2
            self.X_UB = -1
            
        # Set default parameters based on model type
        self._set_default_parameters()
        
    def _set_default_parameters(self):
        """Set default optimization parameters based on model type"""
        if self.MODEL == 1:
            if self.DOWNWIND:
                self.defaults = {
                    'a_s': 0.17, 'b_s': 0.005, 'c_s': 0.2, 'b_f': -0.68, 'c_f': 2.41,
                    'ch1': 0.73, 'ch2': 0.8325, 'ch3': -0.0325, 'ch4': -0.32
                }
                self.pbounds = {
                    'a_s': (0.001, 0.5),
                    'b_s': (0.001, 0.01),
                    'c_s': (0.001, 0.5),
                    'b_f': (-2, 1),
                    'c_f': (0.1, 5),
                    'ch1': (-1, 2),
                    'ch2': (-1, 2),
                    'ch3': (-1, 2),
                    'ch4': (-1, 2),
                }
            else:
                self.defaults = {
                    'ss_alpha': 0.8888888888888888,
                    'ss_beta': 1.4142135623730951,
                    'rp1': -0.672,
                    'rp2': 0.4897,
                    'ng1': -1.381,
                    'ng2': 2.627,
                    'ng3': -1.524,
                    'ng4': 1.336,
                    'fg1': -0.06489,
                    'fg2': 0.4911,
                    'fg3': 1.116,
                    'fg4': -0.1577
                }
                self.pbounds = {
                    'ss_alpha': (0.05, 3),
                    'ss_beta': (0.05, 3),
                    'rp1': (-2, 2),
                    'rp2': (-2, 2),
                    'ng1': (-3, 3),
                    'ng2': (-3, 3),
                    'ng3': (-3, 3),
                    'ng4': (-3, 3),
                    'fg1': (-2, 2),
                    'fg2': (-2, 2),
                    'fg3': (-2, 2),
                    'fg4': (-2, 2)
                }
        else:  # MODEL == 2
            self.defaults = {
                'A': 0.04,
                'cti1': 1.5,
                'cti2': 0.8,
                'ceps': 0.25,
                'ctlim': 0.999,
                'ch1': 0.73,
                'ch2': 0.8325,
                'ch3': -0.0325,
                'ch4': -0.3
            }
            self.pbounds = {
                'A': (0.001, .5),
                'cti1': (.01, 5),
                'cti2': (0.01, 5),
                'ceps': (0.01, 3),
                'ctlim': (0.01, 1),
                'ch1': (-1, 2),
                'ch2': (-1, 2),
                'ch3': (-1, 2),
                'ch4': (-1, 2),
            }


class WakeModelBuilder:
    """Factory class for building wake models with different configurations"""
    
    def __init__(self, site, turbine, config):
        """
        Initialize the wake model builder
        
        Parameters:
        -----------
        site : py_wake.Site
            Site model
        turbine : py_wake.Turbine
            Turbine model
        config : WakeModelConfig
            Configuration object
        """
        self.site = site
        self.turbine = turbine
        self.config = config
        
    def build_wake_deficit_model(self, params=None):
        """
        Build wake deficit model based on configuration and parameters
        
        Parameters:
        -----------
        params : dict
            Model parameters (if None, use defaults)
            
        Returns:
        --------
        wake_deficit_model : py_wake deficit model
        """
        if params is None:
            params = self.config.defaults
            
        if self.config.DOWNWIND:
            if self.config.MODEL == 1:
                def_args = {k: params[k] for k in ['a_s', 'b_s', 'c_s', 'b_f', 'c_f']}
                wake_deficit_model = BlondelSuperGaussianDeficit2020(**def_args)
            else:  # MODEL == 2
                wake_deficit_model = TurboGaussianDeficit(
                    A=params['A'], 
                    cTI=[params['cti1'], params['cti2']],
                    ctlim=params['ctlim'], 
                    ceps=params['ceps'],
                    ct2a=ct2a_mom1d,
                    groundModel=Mirror(),
                    rotorAvgModel=GaussianOverlapAvgModel()
                )
                wake_deficit_model.WS_key = 'WS_jlk'
        else:
            wake_deficit_model = BlondelSuperGaussianDeficit2020()
            
        return wake_deficit_model
        
    def build_blockage_deficit_model(self, params=None):
        """
        Build blockage deficit model based on configuration and parameters
        
        Parameters:
        -----------
        params : dict
            Model parameters (if None, use defaults)
            
        Returns:
        --------
        blockage_deficit_model : py_wake deficit model
        """
        if params is None:
            params = self.config.defaults
            
        if not self.config.DOWNWIND:
            blockage_args = {
                'ss_alpha': params['ss_alpha'], 
                'ss_beta': params['ss_beta'], 
                'r12p': np.array([params['rp1'], params['rp2']]), 
                'ngp': np.array([params['ng1'], params['ng2'], params['ng3'], params['ng4']])
            }
            
            if self.config.MODEL == 2:
                blockage_args['groundModel'] = Mirror()
                
            return SelfSimilarityDeficit2020(**blockage_args)
        else:
            return SelfSimilarityDeficit2020(groundModel=Mirror())
        
    def build_turbulence_model(self, params=None):
        """
        Build turbulence model based on configuration and parameters
        
        Parameters:
        -----------
        params : dict
            Model parameters (if None, use defaults)
            
        Returns:
        --------
        turbulence_model : py_wake turbulence model
        """
        if params is None:
            params = self.config.defaults
            
        if self.config.DOWNWIND:
            turb_args = {'c': np.array([params['ch1'], params['ch2'], params['ch3'], params['ch4']])}
            return CrespoHernandez(**turb_args)
        else:
            return CrespoHernandez()
        
    def build_wind_farm_model(self, params=None):
        """
        Build complete wind farm model based on configuration and parameters
        
        Parameters:
        -----------
        params : dict
            Model parameters (if None, use defaults)
            
        Returns:
        --------
        wfm : py_wake wind farm model
        """
        wake_deficit_model = self.build_wake_deficit_model(params)
        blockage_deficit_model = self.build_blockage_deficit_model(params)
        turbulence_model = self.build_turbulence_model(params)
        
        return All2AllIterative(
            self.site, 
            self.turbine,
            wake_deficitModel=wake_deficit_model,
            superpositionModel=LinearSum(), 
            deflectionModel=None,
            turbulenceModel=turbulence_model,
            blockage_deficitModel=blockage_deficit_model
        )


class WakeModelOptimizer:
    """Class for optimizing wake model parameters"""
    
    def __init__(self, builder, target_data, target_x, target_y, ws_values, ti_values):
        """
        Initialize the optimizer
        
        Parameters:
        -----------
        builder : WakeModelBuilder
            Model builder object
        target_data : xarray.Dataset
            Target data to compare against
        target_x : xarray.DataArray
            X coordinates for evaluations
        target_y : xarray.DataArray
            Y coordinates for evaluations
        ws_values : array-like
            Wind speed values
        ti_values : array-like
            Turbulence intensity values
        """
        self.builder = builder
        self.target_data = target_data
        self.target_x = target_x
        self.target_y = target_y
        
        # Prepare the full WS and TI arrays
        self.ws_values = ws_values
        self.ti_values = ti_values
        self.full_ti = []
        self.full_ws = []
        
        for ws in self.ws_values:
            self.full_ti.extend(self.ti_values)
            self.full_ws.extend([ws] * len(self.ti_values))
            
        self.full_ws = np.array(self.full_ws)
        self.full_ti = np.array(self.full_ti)
        assert len(self.full_ws) == len(self.full_ti)
        
        # Precompute observed values
        self.prepare_observed_values()
        
    def prepare_observed_values(self):
        """Precompute observed deficits for comparison"""
        # Generate reference simulation for CT and TI values
        site = self.builder.site
        turbine = self.builder.turbine
        
        sim_res = All2AllIterative(
            site, 
            turbine,
            wake_deficitModel=BlondelSuperGaussianDeficit2020(),
            superpositionModel=LinearSum(), 
            deflectionModel=None,
            turbulenceModel=CrespoHernandez(),
            blockage_deficitModel=SelfSimilarityDeficit2020()
        )([0], [0], ws=self.full_ws, TI=self.full_ti, wd=[270] * len(self.full_ti), time=True)
        
        flow_map = sim_res.flow_map(HorizontalGrid(x=self.target_x, y=self.target_y))
        
        # Extract observed deficits for each time step
        obs_values = []
        for t in range(flow_map.time.size):
            this_pred_sim = sim_res.isel(time=t, wt=0)
            observed_deficit = self.target_data.deficits.interp(
                ct=this_pred_sim.CT, 
                ti=this_pred_sim.TI, 
                z=0
            )
            obs_values.append(observed_deficit.T)
            
        self.all_obs = xr.concat(obs_values, dim='time')
        
    def evaluate_rmse(self, **kwargs):
        """
        Evaluate RMSE for a set of parameters
        
        Parameters:
        -----------
        **kwargs : dict
            Model parameters
            
        Returns:
        --------
        -rmse : float
            Negative RMSE (for maximization)
        """
        # Build model with provided parameters
        wfm = self.builder.build_wind_farm_model(kwargs)
        
        # Run simulation
        sim_res = wfm(
            [0], [0], 
            ws=self.full_ws, 
            TI=self.full_ti, 
            wd=[270] * len(self.full_ti), 
            time=True
        )
        
        # Create flow map
        flow_map = None
        for tt in range(len(self.full_ws)):
            fm = sim_res.flow_map(
                HorizontalGrid(x=self.target_x, y=self.target_y), 
                time=[tt]
            )['WS_eff']
            
            if flow_map is None:
                flow_map = fm
            else:
                flow_map = xr.concat([flow_map, fm], dim='time')
                
        # Calculate deficits and RMSE
        pred = (sim_res.WS - flow_map.isel(h=0)) / sim_res.WS
        rmse = float(np.sqrt(((self.all_obs - pred) ** 2).mean(['x', 'y'])).mean('time'))
        
        if np.isnan(rmse):
            return -0.5
            
        return -rmse
        
    def optimize(self, init_points=50, n_iter=200):
        """
        Run Bayesian optimization
        
        Parameters:
        -----------
        init_points : int
            Number of initial points for exploration
        n_iter : int
            Number of optimization iterations
            
        Returns:
        --------
        optimizer : BayesianOptimization
            Optimizer object with results
        """
        optimizer = BayesianOptimization(
            f=self.evaluate_rmse, 
            pbounds=self.builder.config.pbounds, 
            random_state=1
        )
        
        optimizer.probe(params=self.builder.config.defaults, lazy=True)
        optimizer.maximize(init_points=init_points, n_iter=n_iter)
        
        return optimizer


class WakeModelAnalyzer:
    """Class for analyzing and visualizing wake model results"""
    
    def __init__(self, builder, optimizer, target_data, target_x, target_y):
        """
        Initialize the analyzer
        
        Parameters:
        -----------
        builder : WakeModelBuilder
            Model builder object
        optimizer : BayesianOptimization
            Optimizer with results
        target_data : xarray.Dataset
            Target data to compare against
        target_x : xarray.DataArray
            X coordinates for evaluations
        target_y : xarray.DataArray
            Y coordinates for evaluations
        """
        self.builder = builder
        self.optimizer = optimizer
        self.target_data = target_data
        self.target_x = target_x
        self.target_y = target_y
        
        self.best_params = optimizer.max['params']
        self.best_rmse = -optimizer.max['target']
        
    def create_optimization_animation(self, output_filename=None):
        """
        Create animation of optimization progress
        
        Parameters:
        -----------
        output_filename : str, optional
            Output filename for the animation (if None, generate based on config)
        """
        if output_filename is None:
            config = self.builder.config
            output_filename = f'optimization_animation_{config.X_LB}_{config.X_UB}.mp4'
            
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
        
        def update_plot(frame):
            ax1.clear()
            ax2.clear()
            
            # Get the best parameters and corresponding RMSE up to the current frame
            best_so_far_params = {}
            best_so_far_rmse = float('inf')
            best_so_far_rmses = []
            
            for i in range(frame + 1):
                if -self.optimizer.space.target[i] <= best_so_far_rmse:
                    best_so_far_rmse = -self.optimizer.space.target[i]
                    best_so_far_params = self.optimizer.res[i]['params']
                best_so_far_rmses.append(best_so_far_rmse)
                
            # Plot the entire history in gray
            ax1.plot(-np.array(self.optimizer.space.target), color='gray', alpha=0.5)
            # Plot the best RMSE so far in black
            ax1.plot(np.array(best_so_far_rmses), color='black')
            ax1.set_title('Optimization Convergence')
            ax1.set_xlabel('Iteration')
            ax1.set_ylabel('RMSE')
            ax1.grid(True)
            
            # Use the best parameters so far for the bar plot
            keys = list(best_so_far_params.keys())
            best_vals = []
            default_vals = []
            
            for key in keys:
                best_vals.append(best_so_far_params[key])
                default_vals.append(self.builder.config.defaults[key])
                
            ax2.bar(keys, best_vals, label='Optimized')
            ax2.bar(keys, default_vals, edgecolor='black', linewidth=2, color='none', 
                   capstyle='butt', label='Default')
            ax2.set_title(f'Best RMSE: {best_so_far_rmse:.4f}')
            ax2.tick_params(axis='x', rotation=45)
            ax2.legend()
            plt.tight_layout()
            
            return ax1, ax2
            
        ani = animation.FuncAnimation(
            fig, 
            update_plot, 
            frames=len(self.optimizer.space.target), 
            repeat=False
        )
        
        # Save as MP4
        writer = animation.FFMpegWriter(fps=15)
        ani.save(output_filename, writer=writer)
        plt.close('all')
        
    def analyze_errors(self, ws_values, ti_values):
        """
        Analyze errors in detail, including average and p90 metrics
        
        Parameters:
        -----------
        ws_values : array-like
            Wind speed values
        ti_values : array-like
            Turbulence intensity values
            
        Returns:
        --------
        error_stats : dict
            Dictionary with error statistics
        """
        config = self.builder.config
        
        # Setup full WS and TI arrays
        full_ti = []
        full_ws = []
        
        for ws in ws_values:
            full_ti.extend(ti_values)
            full_ws.extend([ws] * len(ti_values))
            
        full_ws = np.array(full_ws)
        full_ti = np.array(full_ti)
        
        # Build optimized model
        wfm = self.builder.build_wind_farm_model(self.best_params)
        
        # Run simulation
        sim_res = wfm(
            [0], [0], 
            ws=full_ws, 
            TI=full_ti, 
            wd=[270] * len(full_ti), 
            time=True
        )
        
        # Create flow map
        flow_map = sim_res.flow_map(HorizontalGrid(x=self.target_x, y=self.target_y))
        
        # Analysis variables
        rmse_values = []
        mae_values = []
        bias_values = []
        all_errors = []
        
        # Analyze each time step
        for t in range(flow_map.time.size):
            this_pred_sim = sim_res.isel(time=t)
            observed_deficit = self.target_data.deficits.interp(
                ct=this_pred_sim.CT, 
                ti=this_pred_sim.TI, 
                z=0
            ).isel(wt=0)
            
            pred = (this_pred_sim.WS - flow_map.WS_eff.isel(h=0, time=t)) / this_pred_sim.WS
            diff = observed_deficit.T - pred
            
            # Store errors for this time step
            rmse = np.sqrt(np.mean(diff**2))
            mae = np.mean(np.abs(diff))
            bias = np.mean(diff)
            
            rmse_values.append(rmse)
            mae_values.append(mae)
            bias_values.append(bias)
            all_errors.append(diff.values.flatten())
            
            # Create error plots
            self.plot_error_comparison(
                observed_deficit.T, 
                pred, 
                diff, 
                t, 
                f'figs/{"downstream" if config.DOWNWIND else "upstream"}_err_{t}'
            )
            
        # Calculate overall statistics
        all_errors_flat = np.concatenate(all_errors)
        p90_error = np.percentile(np.abs(all_errors_flat), 90)
        
        error_stats = {
            'mean_rmse': np.mean(rmse_values),
            'mean_mae': np.mean(mae_values),
            'mean_bias': np.mean(bias_values),
            'p90_error': p90_error,
            'rmse_per_case': rmse_values,
            'mae_per_case': mae_values,
            'bias_per_case': bias_values
        }
        
        return error_stats
    
    def plot_error_comparison(self, observed, predicted, difference, time_idx, filename):
        """
        Create comparison plots for observed, predicted, and difference
        
        Parameters:
        -----------
        observed : xarray.DataArray
            Observed deficits
        predicted : xarray.DataArray
            Predicted deficits
        difference : xarray.DataArray
            Difference between observed and predicted
        time_idx : int
            Time index for the plot
        filename : str
            Output filename
        """
        fig, ax = plt.subplots(3, 1, figsize=(5, 15))
        
        co = ax[0].contourf(self.target_x, self.target_y, observed)
        cp = ax[1].contourf(self.target_x, self.target_y, predicted)
        cd = ax[2].contourf(self.target_x, self.target_y, difference)
        
        for jj, c in enumerate([co, cp, cd]):
            fig.colorbar(c, ax=ax[jj])
            
        ax[0].set_ylabel('Observed')
        ax[1].set_ylabel('Prediction')
        ax[2].set_ylabel('Diff')
        
        plt.tight_layout()
        plt.savefig(filename)
        plt.clf()
        
    def plot_parameter_comparison(self, filename=None):
        """
        Create bar plot comparing default and optimized parameters
        
        Parameters:
        -----------
        filename : str, optional
            Output filename (if None, generate based on config)
        """
        if filename is None:
            config = self.builder.config
            filename = f'bar_LB_{config.X_LB}_UP_{config.X_UB}'
            
        keys = self.best_params.keys()
        best_vals = []
        default_vals = []
        
        for key in keys:
            best_vals.append(self.best_params[key])
            default_vals.append(self.builder.config.defaults[key])
            
        plt.figure(figsize=(12, 6))
        plt.bar(keys, best_vals)
        plt.bar(keys, default_vals,
                edgecolor='black',
                linewidth=2,
                color='none',
                capstyle='butt')
                
        plt.title(f'Optimal RMSE: {self.best_rmse:.4f}')
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(filename)
        plt.clf()


def main():
    """Main function to run the wake model analysis"""
    # Load data
    dat = xr.load_dataset('./DTU10MW.nc')
    turbine = DTU10MW()
    D = turbine.diameter()
    dat = dat.assign_coords(x=dat.x * D, y=dat.y * D)
    
    # Create configuration
    config = WakeModelConfig(model_type=2, downwind=True)
    
    # Define region of interest
    roi_x = slice(config.X_LB * D, config.X_UB * D)
    roi_y = slice(-2 * D, 2 * D)
    flow_roi = dat.sel(x=roi_x, y=roi_y)
    target_x = flow_roi.x
    target_y = flow_roi.y
    
    # Define wind speeds and turbulence intensities
    TIs = np.arange(0.05, 0.45, 0.05)
    WSs = np.arange(4, 11)
    
    # Create site and builder
    site = Hornsrev1Site()
    builder = WakeModelBuilder(site, turbine, config)
    
    # Create optimizer
    optimizer = WakeModelOptimizer(
        builder, 
        flow_roi, 
        target_x, 
        target_y, 
        WSs, 
        TIs
    )
    
    # Run optimization
    opt_results = optimizer.optimize(init_points=50, n_iter=200)
    
    # Create analyzer
    analyzer = WakeModelAnalyzer(
        builder, 
        opt_results, 
        flow_roi, 
        target_x, 
        target_y
    )
    
    # Create animation
    analyzer.create_optimization_animation()
    
    # Analyze errors
    error_stats = analyzer.analyze_errors(WSs, TIs)
    
    # Print error statistics
    print(f"Error Statistics:")
    print(f"Overall RMSE: {error_stats['mean_rmse']:.4f}")
    print(f"Overall MAE: {error_stats['mean_mae']:.4f}")
    print(f"Overall Bias: {error_stats['mean_bias']:.4f}")
    print(f"P90 Error: {error_stats['p90_error']:.4f}")
    
    # Plot parameter comparison
    analyzer.plot_parameter_comparison()


if __name__ == "__main__":
    main()

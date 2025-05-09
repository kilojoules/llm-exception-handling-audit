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


class WakeModelOptimizer:
    """Class for optimizing wake model parameters using Bayesian optimization"""
    
    def __init__(self, data_path='./DTU10MW.nc', model_type=2, downwind=True):
        """
        Initialize the optimizer with dataset and model configuration
        
        Parameters:
        -----------
        data_path : str
            Path to the dataset with wake measurements
        model_type : int
            Model type (1: BlondelSuperGaussianDeficit2020, 2: TurboGaussianDeficit)
        downwind : bool
            Whether to focus on downwind (True) or upwind (False) effects
        """
        self.MODEL = model_type
        self.DOWNWIND = downwind
        self.turbine = DTU10MW()
        self.D = self.turbine.diameter()
        self.site = Hornsrev1Site()
        
        # Load and prepare data
        self._load_data(data_path)
        self._setup_simulation_inputs()
        self._define_optimization_bounds()
        
    def _load_data(self, data_path):
        """Load and prepare the dataset"""
        dat = xr.load_dataset(data_path)
        dat = dat.assign_coords(x=dat.x * self.D, y=dat.y * self.D)
        
        # Define region of interest based on downwind/upwind setting
        if self.DOWNWIND:
            X_LB, X_UB = 2, 10
        else:
            X_LB, X_UB = -2, -1
        
        self.X_LB, self.X_UB = X_LB, X_UB
        roi_x = slice(X_LB * self.D, X_UB * self.D)
        roi_y = slice(-2 * self.D, 2 * self.D)
        
        # Extract data in region of interest
        self.flow_roi = dat.sel(x=roi_x, y=roi_y)
        self.target_x = self.flow_roi.x
        self.target_y = self.flow_roi.y
        
    def _setup_simulation_inputs(self):
        """Set up wind speeds, turbulence intensities, and other simulation inputs"""
        # Create arrays of turbulence intensities and wind speeds for simulation
        TIs = np.arange(0.05, 0.45, 0.05)
        WSs = np.arange(4, 11)
        
        # Create full arrays matching each WS with each TI
        full_ti = [TIs for _ in range(WSs.size)]
        self.full_ti = np.array(full_ti).flatten()
        
        full_ws = [[WSs[ii]] * TIs.size for ii in range(WSs.size)]
        self.full_ws = np.array(full_ws).flatten()
        
        assert (self.full_ws.size == self.full_ti.size)
        
        # Generate observation values from reference simulation
        self._generate_observation_values()
        
    def _generate_observation_values(self):
        """Generate reference observation values from the simulation"""
        sim_res = All2AllIterative(
            self.site, self.turbine,
            wake_deficitModel=BlondelSuperGaussianDeficit2020(),
            superpositionModel=LinearSum(), 
            deflectionModel=None,
            turbulenceModel=CrespoHernandez(),
            blockage_deficitModel=SelfSimilarityDeficit2020()
        )([0], [0], ws=self.full_ws, TI=self.full_ti, wd=[270] * self.full_ti.size, time=True)
        
        # Create flow map for the region of interest
        self.flow_map = sim_res.flow_map(HorizontalGrid(x=self.target_x, y=self.target_y))
        
        # Extract observation values
        obs_values = []
        for t in range(self.flow_map.time.size):
            this_pred_sim = sim_res.isel(time=t, wt=0)
            observed_deficit = self.flow_roi.deficits.interp(
                ct=this_pred_sim.CT, 
                ti=this_pred_sim.TI, 
                z=0
            )
            obs_values.append(observed_deficit.T)
        
        self.all_obs = xr.concat(obs_values, dim='time')
    
    def _define_optimization_bounds(self):
        """Define the parameter bounds and defaults for optimization"""
        # Define defaults and bounds based on model type and downwind/upwind configuration
        if self.MODEL == 1:
            if self.DOWNWIND:
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
                self.defaults = {
                    'a_s': 0.17, 'b_s': 0.005, 'c_s': 0.2, 'b_f': -0.68, 'c_f': 2.41,
                    'ch1': 0.73, 'ch2': 0.8325, 'ch3': -0.0325, 'ch4': -0.32
                }
            else:
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
    
    def create_wind_farm_model(self, params):
        """
        Create a wind farm model with the given parameters
        
        Parameters:
        -----------
        params : dict
            Dictionary of parameters for the wind farm model
            
        Returns:
        --------
        wfm : All2AllIterative
            Configured wind farm model
        """
        if self.DOWNWIND:
            if self.MODEL == 1:
                def_args = {k: params[k] for k in ['a_s', 'b_s', 'c_s', 'b_f', 'c_f']}
                turb_args = {'c': np.array([params['ch1'], params['ch2'], params['ch3'], params['ch4']])}
                blockage_args = {}
                wake_deficitModel = BlondelSuperGaussianDeficit2020(**def_args)
            else:  # MODEL == 2
                turb_args = {'c': np.array([params['ch1'], params['ch2'], params['ch3'], params['ch4']])}
                wake_deficitModel = TurboGaussianDeficit(
                    A=params['A'], 
                    cTI=[params['cti1'], params['cti2']],
                    ctlim=params['ctlim'], 
                    ceps=params['ceps'],
                    ct2a=ct2a_mom1d,
                    groundModel=Mirror(),
                    rotorAvgModel=GaussianOverlapAvgModel()
                )
                wake_deficitModel.WS_key = 'WS_jlk'
                blockage_args = {}
        else:  # UPWIND
            def_args = {}
            turb_args = {}
            wake_deficitModel = BlondelSuperGaussianDeficit2020(**def_args)
            
            blockage_args = {
                'ss_alpha': params['ss_alpha'], 
                'ss_beta': params['ss_beta'], 
                'r12p': np.array([params['rp1'], params['rp2']]), 
                'ngp': np.array([params['ng1'], params['ng2'], params['ng3'], params['ng4']])
            }
            
            if self.MODEL == 2:
                blockage_args['groundModel'] = Mirror()
        
        # Create and return the wind farm model
        wfm = All2AllIterative(
            self.site, self.turbine,
            wake_deficitModel=wake_deficitModel,
            superpositionModel=LinearSum(), 
            deflectionModel=None,
            turbulenceModel=CrespoHernandez(**turb_args),
            blockage_deficitModel=SelfSimilarityDeficit2020(**blockage_args)
        )
        
        return wfm
    
    def evaluate_rmse(self, **kwargs):
        """
        Evaluate RMSE for given parameters
        
        Parameters:
        -----------
        **kwargs : dict
            Dictionary of parameters to evaluate
            
        Returns:
        --------
        float
            Negative RMSE (for maximization in Bayesian optimization)
        """
        # Create wind farm model with the given parameters
        wfm = self.create_wind_farm_model(kwargs)
        
        # Run simulation
        sim_res = wfm(
            [0], [0], 
            ws=self.full_ws, 
            TI=self.full_ti, 
            wd=[270] * self.full_ti.size, 
            time=True
        )
        
        # Create flow map
        flow_map = None
        for tt in range(self.full_ws.size):
            fm = sim_res.flow_map(HorizontalGrid(x=self.target_x, y=self.target_y), time=[tt])['WS_eff']
            if flow_map is None:
                flow_map = fm
            else:
                flow_map = xr.concat([flow_map, fm], dim='time')
        
        # Calculate prediction deficits
        pred = (sim_res.WS - flow_map.isel(h=0)) / sim_res.WS
        
        # Calculate RMSE
        rmse = float(np.sqrt(((self.all_obs - pred) ** 2).mean(['x', 'y'])).mean('time'))
        
        # Return negative RMSE for maximization
        if np.isnan(rmse): 
            return -0.5
        
        return -rmse
    
    def run_optimization(self, init_points=50, n_iter=200):
        """
        Run Bayesian optimization
        
        Parameters:
        -----------
        init_points : int
            Number of initial random points
        n_iter : int
            Number of optimization iterations
            
        Returns:
        --------
        dict
            Best parameters and corresponding RMSE
        """
        # Create and run optimizer
        self.optimizer = BayesianOptimization(
            f=self.evaluate_rmse, 
            pbounds=self.pbounds, 
            random_state=1
        )
        
        # Probe default parameters
        self.optimizer.probe(params=self.defaults, lazy=True)
        
        # Run optimization
        self.optimizer.maximize(init_points=init_points, n_iter=n_iter)
        
        # Get best parameters and RMSE
        self.best_params = self.optimizer.max['params']
        self.best_rmse = -self.optimizer.max['target']
        
        return {
            'params': self.best_params,
            'rmse': self.best_rmse
        }
    
    def create_optimization_animation(self, filename=None):
        """
        Create animation of optimization progress
        
        Parameters:
        -----------
        filename : str, optional
            Filename to save animation, if None, uses default name
        """
        if filename is None:
            filename = f'optimization_animation_{self.X_LB}_{self.X_UB}.mp4'
        
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
                default_vals.append(self.defaults[key])
            
            ax2.bar(keys, best_vals, label='Optimized')
            ax2.bar(keys, default_vals, edgecolor='black', linewidth=2, color='none', 
                   capstyle='butt', label='Default')
            ax2.set_title(f'Best RMSE: {best_so_far_rmse:.4f}')
            ax2.tick_params(axis='x', rotation=45)
            ax2.legend()
            
            plt.tight_layout()
            return ax1, ax2
        
        ani = animation.FuncAnimation(
            fig, update_plot, 
            frames=len(self.optimizer.space.target), 
            repeat=False
        )
        
        # Save as MP4
        writer = animation.FFMpegWriter(fps=15)
        ani.save(filename, writer=writer)
        plt.close('all')
    
    def evaluate_best_model(self):
        """
        Evaluate the best model and generate visualizations
        
        Returns:
        --------
        float
            Overall RMSE
        list
            RMSE values for each time step
        """
        # Create wind farm model with best parameters
        wfm = self.create_wind_farm_model(self.best_params)
        
        # Run simulation
        sim_res = wfm(
            [0], [0], 
            ws=self.full_ws, 
            TI=self.full_ti, 
            wd=[270] * self.full_ti.size, 
            time=True
        )
        
        # Calculate RMSE for each time step
        rmse_values = []
        
        for t in range(self.flow_map.time.size):
            this_pred_sim = sim_res.isel(time=t)
            observed_deficit = self.flow_roi.deficits.interp(
                ct=this_pred_sim.CT, 
                ti=this_pred_sim.TI, 
                z=0
            ).isel(wt=0)
            
            # Calculate prediction deficit
            pred = (this_pred_sim.WS - self.flow_map.WS_eff.isel(h=0, time=t)) / this_pred_sim.WS
            
            # Calculate difference and RMSE
            diff = observed_deficit.T - pred
            rmse = np.sqrt(np.mean(diff**2))
            rmse_values.append(rmse)
            
            # Create visualization
            self._plot_comparison(t, observed_deficit.T, pred, diff)
        
        # Calculate overall RMSE
        overall_rmse = np.mean(rmse_values)
        
        print(f"RMSE values per time step: {rmse_values}")
        print(f"Overall RMSE: {overall_rmse}")
        print(f"p90 of errors: {np.percentile(rmse_values, 90)}")
        
        # Create parameter comparison plot
        self._plot_parameter_comparison()
        
        return overall_rmse, rmse_values
    
    def _plot_comparison(self, t, observed, predicted, difference):
        """
        Plot comparison between observed, predicted, and difference
        
        Parameters:
        -----------
        t : int
            Time step
        observed : xarray.DataArray
            Observed deficit
        predicted : xarray.DataArray
            Predicted deficit
        difference : xarray.DataArray
            Difference between observed and predicted
        """
        fig, ax = plt.subplots(3, 1, figsize=(8, 16))
        
        # Plot observed deficit
        co = ax[0].contourf(self.target_x, self.target_y, observed)
        fig.colorbar(co, ax=ax[0])
        ax[0].set_ylabel('Observed')
        ax[0].set_title(f'Observed Velocity Deficit (Time Step {t})')
        
        # Plot predicted deficit
        cp = ax[1].contourf(self.target_x, self.target_y, predicted)
        fig.colorbar(cp, ax=ax[1])
        ax[1].set_ylabel('Prediction')
        ax[1].set_title(f'Predicted Velocity Deficit (Time Step {t})')
        
        # Plot difference
        vmax = np.max(np.abs(difference))
        cd = ax[2].contourf(self.target_x, self.target_y, difference, 
                           cmap='RdBu_r', vmin=-vmax, vmax=vmax)
        fig.colorbar(cd, ax=ax[2])
        ax[2].set_ylabel('Difference')
        ax[2].set_title(f'Difference (Observed - Predicted)')
        ax[2].set_xlabel('x/D')
        
        plt.tight_layout()
        
        direction = "downstream" if self.DOWNWIND else "upstream"
        plt.savefig(f'figs/{direction}_err_{t}.png')
        plt.close()
    
    def _plot_parameter_comparison(self):
        """Plot comparison between default and optimized parameters"""
        plt.figure(figsize=(12, 6))
        
        keys = self.best_params.keys()
        best_vals = []
        default_vals = []
        
        for key in keys:
            best_vals.append(self.best_params[key])
            default_vals.append(self.defaults[key])
        
        plt.bar(keys, best_vals, label='Optimized')
        plt.bar(keys, default_vals,
              edgecolor='black',
              linewidth=2,
              color='none',
              capstyle='butt',
              label='Default')
        
        plt.title(f'Parameter Comparison (Optimal RMSE: {self.best_rmse:.4f})')
        plt.xticks(rotation=45)
        plt.legend()
        plt.tight_layout()
        
        plt.savefig(f'bar_LB_{self.X_LB}_UP_{self.X_UB}.png')
        plt.close()


def main():
    """Main function to run the optimization"""
    # Set configuration
    model_type = 2  # 1: BlondelSuperGaussianDeficit2020, 2: TurboGaussianDeficit
    downwind = True  # True: focus on downwind effects, False: focus on upwind effects
    
    # Create optimizer
    optimizer = WakeModelOptimizer(
        data_path='./DTU10MW.nc',
        model_type=model_type,
        downwind=downwind
    )
    
    # Run optimization
    results = optimizer.run_optimization(init_points=50, n_iter=200)
    
    # Create optimization animation
    optimizer.create_optimization_animation()
    
    # Evaluate best model
    overall_rmse, rmse_values = optimizer.evaluate_best_model()
    
    # Print results
    print(f"Best parameters: {results['params']}")
    print(f"Best RMSE: {results['rmse']}")
    print(f"Average RMSE: {overall_rmse}")
    print(f"P90 of RMSE: {np.percentile(rmse_values, 90)}")


if __name__ == "__main__":
    main()

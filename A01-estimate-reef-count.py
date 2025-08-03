"""
Reef Count Estimation using Monte Carlo Analysis
-----------------------------------------------

PURPOSE:
    This script estimates the number of reef features in the Coral Sea dataset,
    accounting for spatial accuracy and feature classification uncertainty.
    It uses a Monte Carlo approach to generate a statistical distribution of
    the likely number of reefs based on confidence attributes.
    
    The analysis is performed across a range of area thresholds to assess
    sensitivity of reef count to the minimum size criteria.

INPUTS:
    - Coral Sea reef shapefile with EdgeAcc_m and TypeConf attributes
      - EdgeAcc_m: 90th percentile spatial error of boundary in meters
      - TypeConf: Confidence in reef classification (Very high, High, Medium, Low)

OUTPUTS:
    - Statistical estimates of reef count with confidence intervals across multiple area thresholds
    - Trial results for each Monte Carlo iteration at each threshold
    - Summary plot showing reef count vs area threshold
    - Histogram distributions for selected thresholds

ALGORITHM:
    1. Load the Coral Sea reef shapefile
    2. Reproject from EPSG:4326 to EPSG:3112 for accurate area calculation
    3. For each reef feature:
       a. Create two buffered versions (+/- EdgeAcc_m/4) to account for boundary uncertainty
       b. Convert TypeConf values to probability percentages
    4. For each area threshold in a geometric progression from 0.01 to 1 km²:
       a. Run Monte Carlo simulation (200 trials per threshold):
          i. For each feature, randomly determine if it's a real reef based on TypeConf
          ii. Randomly select one of the polygon versions (original, larger, smaller)
          iii. Count the feature only if area > threshold
       b. Calculate summary statistics (mean, standard deviation, 95% CI)
    5. Generate visualizations:
       a. Plot mean reef count with 95% CI vs area threshold
       b. Generate histograms for selected area thresholds
"""

import os
import geopandas as gpd
import numpy as np
import random
from tqdm import tqdm
import matplotlib.pyplot as plt
from shapely.errors import ShapelyError
import configparser
import sys
import pandas as pd
from matplotlib.ticker import ScalarFormatter

# Define input and output paths - updated to use config file
# Read configuration file for file paths
config = configparser.ConfigParser()
try:
    config.read('config.ini')
    download_path = config.get('general', 'in_3p_path')
    INPUT_SHAPE = os.path.join(download_path, 'Coral-Sea-Feat', 'Reefs-Cays',
                              'CS_AIMS_Coral-Sea-Features_2025_Reefs-cays.shp')
    print(f"Using Coral Sea reef data: {INPUT_SHAPE}")
except (configparser.Error, KeyError):
    print("ERROR: Could not read config file or missing 'in_3p_path' entry.")
    print("Please ensure the config.ini file exists and contains the correct path.")
    sys.exit(1)

OUTPUT_DIR = "working/07"
NUM_TRIALS = 200  # Monte Carlo trials

# Create geometric progression of area thresholds from 0.01 to 1 km²
MIN_AREA_KM2 = 0.01  # 0.01 km²
MAX_AREA_KM2 = 1.0   # 1 km²
NUM_THRESHOLDS = 20   # 20 steps in geometric progression

# Calculate the geometric progression
AREA_THRESHOLDS_KM2 = np.geomspace(MIN_AREA_KM2, MAX_AREA_KM2, NUM_THRESHOLDS)
AREA_THRESHOLDS_M2 = AREA_THRESHOLDS_KM2 * 1_000_000  # Convert to m²

# Create output directory if it doesn't exist
os.makedirs(OUTPUT_DIR, exist_ok=True)

# TypeConf to probability mapping
TYPECONF_PROBABILITY = {
    "Very high": 0.99,  # 99% chance it's a reef
    "High": 0.94,      # 94% chance it's a reef
    "Medium": 0.75,    # 75% chance it's a reef
    "Low": 0.60        # 60% chance it's a reef
}

def prepare_data():
    """Load and prepare the reef data with buffered versions"""
    if not os.path.exists(INPUT_SHAPE):
        print(f"ERROR: Input shapefile not found: {INPUT_SHAPE}")
        print("Please check that the path is correct and the file exists.")
        return None
    
    print(f"Loading reef shapefile from {INPUT_SHAPE}")
    try:
        reefs = gpd.read_file(INPUT_SHAPE)
    except Exception as e:
        print(f"Error reading shapefile: {e}")
        return None
    
    # Check that required attributes exist
    required_attrs = ['EdgeAcc_m', 'TypeConf']
    missing_attrs = [attr for attr in required_attrs if attr not in reefs.columns]
    
    if missing_attrs:
        print(f"Warning: The following required attributes are missing: {', '.join(missing_attrs)}")
        # Add missing attributes with default values
        for attr in missing_attrs:
            if attr == 'EdgeAcc_m':
                print("Adding default EdgeAcc_m attribute with value 10m")
                reefs['EdgeAcc_m'] = 10
            elif attr == 'TypeConf':
                print("Adding default TypeConf attribute with value 'Medium'")
                reefs['TypeConf'] = 'Medium'
        print("Continuing with added default attributes...")
    
    print(f"Loaded {len(reefs)} reef features")
    
    # Reproject to EPSG:3112 (Australian Albers) for accurate area calculation
    print("Reprojecting to EPSG:3112 for accurate area calculation...")
    reefs = reefs.to_crs(epsg=3112)
    
    # Calculate the original area
    reefs['area_m2'] = reefs.geometry.area
    
    # Create buffered versions of each polygon
    print("Creating buffered versions of each polygon to account for spatial uncertainty...")
    reefs_with_buffers = []
    
    for idx, reef in tqdm(reefs.iterrows(), total=len(reefs), desc="Creating buffers"):
        edge_acc = reef.get('EdgeAcc_m', 0)
        typeconf = reef.get('TypeConf', 'Low')
        
        # If EdgeAcc_m is missing, use a default value or skip
        if edge_acc is None or edge_acc <= 0:
            edge_acc = 10  # Default value if missing
        
        # If TypeConf is missing, use the most conservative value
        if typeconf not in TYPECONF_PROBABILITY:
            typeconf = "Low"
        
        buffer_dist = edge_acc / 4
        
        # Create a dictionary for this feature with original and buffered geometries
        feature_dict = {
            'id': idx,
            'EdgeAcc_m': edge_acc,
            'TypeConf': typeconf,
            'reef_prob': TYPECONF_PROBABILITY.get(typeconf, 0.5),
            'original_geom': reef.geometry,
            'original_area': reef.geometry.area
        }
        
        # Create larger polygon (positive buffer)
        try:
            larger_geom = reef.geometry.buffer(buffer_dist)
            feature_dict['larger_geom'] = larger_geom
            feature_dict['larger_area'] = larger_geom.area
        except Exception as e:
            print(f"Warning: Error creating positive buffer for feature {idx}: {e}")
            feature_dict['larger_geom'] = reef.geometry
            feature_dict['larger_area'] = reef.geometry.area
        
        # Create smaller polygon (negative buffer)
        try:
            smaller_geom = reef.geometry.buffer(-buffer_dist)
            # Check if negative buffer resulted in empty or invalid geometry
            if smaller_geom.is_empty or not smaller_geom.is_valid:
                # Use a very small buffer instead
                smaller_geom = reef.geometry.buffer(-buffer_dist/10)
                if smaller_geom.is_empty or not smaller_geom.is_valid:
                    smaller_geom = reef.geometry  # Fall back to original if still invalid
            feature_dict['smaller_geom'] = smaller_geom
            feature_dict['smaller_area'] = smaller_geom.area
        except Exception as e:
            print(f"Warning: Error creating negative buffer for feature {idx}: {e}")
            feature_dict['smaller_geom'] = reef.geometry
            feature_dict['smaller_area'] = reef.geometry.area
        
        reefs_with_buffers.append(feature_dict)
    
    print(f"Created buffered versions for {len(reefs_with_buffers)} features")
    return reefs_with_buffers

def run_monte_carlo(reef_data, area_threshold_m2, num_trials=200):
    """Run Monte Carlo simulation to estimate reef count using specified area threshold"""
    if not reef_data:
        return None
    
    trial_results = []
    
    # Use tqdm for progress tracking
    for trial in tqdm(range(num_trials), desc=f"Monte Carlo Trials (Threshold: {area_threshold_m2/1_000_000:.3f} km²)", leave=False):
        # Reset counters for this trial
        reef_count = 0
        
        # Process each reef feature
        for reef in reef_data:
            # Step 1: Determine if this is actually a reef based on TypeConf probability
            is_reef = random.random() < reef['reef_prob']
            
            if is_reef:
                # Step 2: Randomly select which polygon version to use
                polygon_choice = random.choice(['original', 'larger', 'smaller'])
                
                # Get the area for the selected polygon version
                area = reef[f'{polygon_choice}_area']
                
                # Step 3: Count the reef only if it meets the area threshold
                if area > area_threshold_m2:
                    reef_count += 1
        
        trial_results.append(reef_count)
    
    return trial_results

def analyze_results(trial_results, area_threshold_km2, generate_hist=False, threshold_index=None, total_thresholds=None):
    """Analyze the Monte Carlo trial results for a specific area threshold"""
    if not trial_results:
        return None
    
    # Calculate statistics
    mean_count = np.mean(trial_results)
    std_dev = np.std(trial_results)
    ci_lower = mean_count - 2 * std_dev
    ci_upper = mean_count + 2 * std_dev
    
    # Create a dictionary with the results
    results = {
        'area_threshold_km2': area_threshold_km2,
        'mean_count': mean_count,
        'std_dev': std_dev,
        'ci_lower': ci_lower,
        'ci_upper': ci_upper,
        'trial_results': trial_results
    }
    
    # Generate histogram for selected thresholds (every 5th one)
    if generate_hist:
        plt.figure(figsize=(10, 6))
        plt.hist(trial_results, bins=range(min(trial_results), max(trial_results) + 2), alpha=0.7)
        plt.axvline(mean_count, color='red', linestyle='dashed', linewidth=2, label=f'Mean: {mean_count:.1f}')
        plt.axvline(ci_lower, color='green', linestyle='dashed', linewidth=1, label=f'95% CI Lower: {ci_lower:.1f}')
        plt.axvline(ci_upper, color='green', linestyle='dashed', linewidth=1, label=f'95% CI Upper: {ci_upper:.1f}')
        
        plt.title(f'Monte Carlo Reef Count Estimation (Area Threshold: {area_threshold_km2:.3f} km²)')
        plt.xlabel('Estimated Reef Count')
        plt.ylabel('Frequency')
        plt.grid(axis='y', alpha=0.3)
        plt.legend()
        
        # Save the plot
        output_plot = os.path.join(OUTPUT_DIR, f'reef_count_histogram_threshold_{threshold_index}.png')
        plt.savefig(output_plot)
        plt.close()
        print(f"Saved histogram for threshold {threshold_index}/{total_thresholds} ({area_threshold_km2:.3f} km²)")
    
    return results

def plot_threshold_results(all_results):
    """Create a plot showing how reef count changes with area threshold"""
    # Extract data from results
    thresholds = [r['area_threshold_km2'] for r in all_results]
    means = [r['mean_count'] for r in all_results]
    ci_lower = [r['ci_lower'] for r in all_results]
    ci_upper = [r['ci_upper'] for r in all_results]
    
    # Create the plot
    plt.figure(figsize=(12, 8))
    
    # Plot mean line
    plt.plot(thresholds, means, 'b-', linewidth=2, label='Mean Reef Count')
    
    # Plot confidence interval
    plt.fill_between(thresholds, ci_lower, ci_upper, color='b', alpha=0.2, label='95% Confidence Interval')
    
    # Set x-axis to logarithmic scale for better visualization
    plt.xscale('log')
    
    # Format x-axis to show actual values instead of powers of 10
    plt.gca().xaxis.set_major_formatter(ScalarFormatter())
    
    # Add labels and title
    plt.grid(True, alpha=0.3)
    plt.xlabel('Area Threshold (km²)')
    plt.ylabel('Estimated Reef Count')
    plt.title('Sensitivity of Reef Count Estimate to Area Threshold')
    plt.legend()
    
    # Add annotations for selected thresholds
    for i in range(0, len(thresholds), 4):
        plt.annotate(f'{thresholds[i]:.3f} km²',
                     xy=(thresholds[i], means[i]),
                     xytext=(0, 10),
                     textcoords='offset points',
                     ha='center',
                     fontsize=8)
    
    # Save the plot
    output_plot = os.path.join(OUTPUT_DIR, 'reef_count_vs_threshold.png')
    plt.tight_layout()
    plt.savefig(output_plot)
    plt.close()
    print(f"Saved reef count vs threshold plot to {output_plot}")

def save_results_to_csv(all_results):
    """Save the summary results to a CSV file"""
    # Create a DataFrame for the summary statistics
    summary_df = pd.DataFrame([{
        'area_threshold_km2': r['area_threshold_km2'],
        'mean_count': r['mean_count'],
        'std_dev': r['std_dev'],
        'ci_lower': r['ci_lower'],
        'ci_upper': r['ci_upper']
    } for r in all_results])
    
    # Save to CSV
    summary_csv = os.path.join(OUTPUT_DIR, 'reef_count_threshold_summary.csv')
    summary_df.to_csv(summary_csv, index=False)
    print(f"Saved summary results to {summary_csv}")
    
    # Save individual trial results for each threshold
    # for i, result in enumerate(all_results):
    #     trials_df = pd.DataFrame({
    #         'trial': range(1, len(result['trial_results']) + 1),
    #         'reef_count': result['trial_results'],
    #         'area_threshold_km2': result['area_threshold_km2']
    #     })
        
    #     # Add to a single large DataFrame or save individually
    #     trials_csv = os.path.join(OUTPUT_DIR, f'reef_count_trials_threshold_{i+1}.csv')
    #     trials_df.to_csv(trials_csv, index=False)
    
    # Also create a consolidated file with all trials
    all_trials = []
    for i, result in enumerate(all_results):
        for j, count in enumerate(result['trial_results']):
            all_trials.append({
                'threshold_index': i+1,
                'area_threshold_km2': result['area_threshold_km2'],
                'trial': j+1,
                'reef_count': count
            })
    
    all_trials_df = pd.DataFrame(all_trials)
    all_trials_csv = os.path.join(OUTPUT_DIR, 'reef_count_all_trials.csv')
    all_trials_df.to_csv(all_trials_csv, index=False)
    print(f"Saved all trial results to {all_trials_csv}")

def main():
    # Prepare the data (only needs to be done once)
    print("Preparing reef data...")
    reef_data = prepare_data()
    
    if reef_data:
        print(f"Running sensitivity analysis across {NUM_THRESHOLDS} area thresholds from {MIN_AREA_KM2} to {MAX_AREA_KM2} km²")
        
        # Storage for results across all thresholds
        all_results = []
        
        # Iterate through area thresholds
        for i, area_threshold_km2 in enumerate(AREA_THRESHOLDS_KM2):
            area_threshold_m2 = area_threshold_km2 * 1_000_000
            
            print(f"\nProcessing area threshold {i+1}/{NUM_THRESHOLDS}: {area_threshold_km2:.3f} km²")
            
            # Run Monte Carlo simulation for this threshold
            trial_results = run_monte_carlo(reef_data, area_threshold_m2, NUM_TRIALS)
            
            # Determine if we should generate a histogram for this threshold (every 5th one)
            generate_hist = (i % 5 == 0)
            
            # Analyze the results
            results = analyze_results(trial_results, area_threshold_km2, 
                                     generate_hist=generate_hist, 
                                     threshold_index=i+1, 
                                     total_thresholds=NUM_THRESHOLDS)
            
            # Add to our collection of results
            all_results.append(results)
            
            # Print a brief summary for this threshold
            print(f"Area threshold {area_threshold_km2:.3f} km²: Mean reef count = {results['mean_count']:.1f}, " +
                  f"95% CI: [{results['ci_lower']:.1f}, {results['ci_upper']:.1f}]")
        
        # Create summary plot showing reef count vs threshold
        plot_threshold_results(all_results)
        
        # Save all results to CSV files
        save_results_to_csv(all_results)
        
        print("\nSensitivity analysis complete!")
    else:
        print("Error: Could not prepare reef data. Exiting.")

if __name__ == "__main__":
    main()


"""
This script analyzes the attributes of the GIS file, reporting on their characteristics
to help determine optimal field sizes for a schema.

The goal of this script is to help design a schema for the dataset shapefile that
will minimise the size of the attributes table.

The script reads the input file from the output of script 06 and reports:
- String fields: maximum length and example of longest value
- Numeric fields: whether integer or float, range, decimal precision
- Suggested field sizes for creating an optimized schema
"""

import os
import sys
import pandas as pd
import geopandas as gpd
import numpy as np
from collections import OrderedDict

# Define input path
INPUT_FILE = "working/06/TS-GBR-CS-NW-Features-corrected.shp"

def analyze_attributes(gdf):
    """Analyze all attributes in a GeoDataFrame and return metadata about them"""
    attribute_info = OrderedDict()
    
    # Process each attribute
    for column in gdf.columns:
        # Skip the geometry column
        if column == 'geometry':
            continue
        
        col_type = gdf[column].dtype
        
        if pd.api.types.is_string_dtype(gdf[column]) or pd.api.types.is_object_dtype(gdf[column]):
            # Handle string columns
            non_null_values = gdf[column].dropna().astype(str)
            
            if len(non_null_values) > 0:
                max_length = non_null_values.str.len().max()
                longest_value = non_null_values[non_null_values.str.len() == max_length].iloc[0]
                unique_count = gdf[column].nunique()
                
                attribute_info[column] = {
                    'type': 'string',
                    'max_length': max_length,
                    'longest_value': longest_value,
                    'unique_values': unique_count,
                    'sample_values': gdf[column].dropna().unique()[:5].tolist()
                }
            else:
                attribute_info[column] = {
                    'type': 'string',
                    'max_length': 0,
                    'longest_value': None,
                    'unique_values': 0,
                    'sample_values': []
                }
                
        elif pd.api.types.is_integer_dtype(col_type):
            # Handle integer columns
            attribute_info[column] = {
                'type': 'integer',
                'min': gdf[column].min() if not gdf[column].isna().all() else None,
                'max': gdf[column].max() if not gdf[column].isna().all() else None,
                'unique_values': gdf[column].nunique(),
                'sample_values': gdf[column].dropna().unique()[:5].tolist()
            }
            
        elif pd.api.types.is_float_dtype(col_type):
            # Handle float columns
            non_null = gdf[column].dropna()
            
            # Check if the float column contains only integers
            is_integer = False
            if len(non_null) > 0:
                is_integer = np.allclose(non_null, non_null.round())
            
            # Get decimal precision
            if len(non_null) > 0:
                # Convert to strings and find the maximum number of decimal places
                str_vals = non_null.astype(str)
                # Extract decimal parts
                decimal_parts = str_vals.str.extract(r'\.(\d+)')
                max_decimals = decimal_parts[0].str.len().max() if not decimal_parts[0].isna().all() else 0
            else:
                max_decimals = 0
                
            attribute_info[column] = {
                'type': 'integer' if is_integer else 'float',
                'min': non_null.min() if len(non_null) > 0 else None,
                'max': non_null.max() if len(non_null) > 0 else None,
                'decimals': max_decimals,
                'unique_values': gdf[column].nunique(),
                'sample_values': gdf[column].dropna().unique()[:5].tolist()
            }
            
        else:
            # Handle other data types
            attribute_info[column] = {
                'type': str(col_type),
                'unique_values': gdf[column].nunique(),
                'sample_values': gdf[column].dropna().unique()[:5].tolist()
            }
    
    return attribute_info

def print_attribute_info(attribute_info, gdf):
    """Print the attribute information in a readable format"""
    print("\n=== ATTRIBUTE ANALYSIS ===")
    
    for attr_name, info in attribute_info.items():
        print(f"\n{attr_name}:")
        print(f"  Type: {info['type']}")
        
        if info['type'] == 'string':
            print(f"  Max Length: {info['max_length']}")
            if info['longest_value']:
                # Truncate longest value if it's too long for display
                display_value = info['longest_value']
                if len(display_value) > 50:
                    display_value = display_value[:47] + "..."
                print(f"  Longest Value: '{display_value}'")
            print(f"  Unique Values: {info['unique_values']}")
            
            if info['unique_values'] <= 10:
                print(f"  All Values: {sorted(gdf[attr_name].dropna().unique().tolist())}")
            else:
                print(f"  Sample Values: {info['sample_values']}")
                
        elif info['type'] == 'integer':
            print(f"  Range: {info['min']} to {info['max']}")
            print(f"  Unique Values: {info['unique_values']}")
            if info['unique_values'] <= 10:
                print(f"  All Values: {sorted(gdf[attr_name].dropna().unique().tolist())}")
            else:
                print(f"  Sample Values: {info['sample_values']}")
                
        elif info['type'] == 'float':
            print(f"  Range: {info['min']} to {info['max']}")
            print(f"  Decimal Places: {info['decimals']}")
            print(f"  Unique Values: {info['unique_values']}")
            if info['unique_values'] <= 10:
                print(f"  All Values: {sorted(gdf[attr_name].dropna().unique().tolist())}")
            else:
                print(f"  Sample Values: {info['sample_values']}")
    
    # Print schema suggestion
    print("\n=== SUGGESTED SCHEMA ===")
    print("schema = {")
    print(f"    'geometry': '{gdf.geometry.iloc[0].geom_type}',")
    print("    'properties': {")
    
    for attr_name, info in attribute_info.items():
        if info['type'] == 'string':
            # Add a buffer to max length to be safe
            suggested_length = min(254, info['max_length'] + 5)
            print(f"        '{attr_name}': 'str:{suggested_length}',")
        elif info['type'] == 'integer':
            print(f"        '{attr_name}': 'int',")
        elif info['type'] == 'float':
            # Suggest width based on the maximum value and decimal places
            max_val = info['max'] if info['max'] is not None else 0
            min_val = info['min'] if info['min'] is not None else 0
            max_abs = max(abs(max_val), abs(min_val))
            
            # Calculate width needed for the integer part + decimal point + decimal places
            width = len(str(int(max_abs))) + 1 + info['decimals']
            precision = info['decimals']
            
            print(f"        '{attr_name}': 'float:{width}.{precision}',")
    
    print("    }")
    print("}")

def main():
    """Main function to run the attribute analysis"""
    if not os.path.exists(INPUT_FILE):
        print(f"Error: Input file '{INPUT_FILE}' not found")
        print("Please run script 06 first or check the file path")
        sys.exit(1)
    
    print(f"Analyzing attributes in {INPUT_FILE}")
    try:
        gdf = gpd.read_file(INPUT_FILE)
        print(f"Successfully loaded file with {len(gdf)} features")
        
        attribute_info = analyze_attributes(gdf)
        print_attribute_info(attribute_info, gdf)
        
    except Exception as e:
        print(f"Error analyzing shapefile: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
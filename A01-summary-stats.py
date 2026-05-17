import geopandas as gpd
import os

INPUT_SHP = "data/v0-1/out/AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_v0-1.shp"
OUTPUT_SHP = "working/A01/Aus-Trop-Reef-Features_v0-1_RB-Type-L2.shp"

# Ensure output directory exists
os.makedirs(os.path.dirname(OUTPUT_SHP), exist_ok=True)

# Load the shapefile
gdf = gpd.read_file(INPUT_SHP)

# Group by RB_Type_L3, calculate total area and feature count
summary = (
    gdf.groupby("RB_Type_L3")
       .agg(
           Feature_Count=("RB_Type_L3", "count"),
           Total_Area_km2=("Area_km2", "sum")
       )
       .reset_index()
       .sort_values("Total_Area_km2", ascending=False)
)

# Print or export the summary
print(summary)

summary = (
    gdf.groupby("RB_Type_L2")
       .agg(
           Feature_Count=("RB_Type_L2", "count"),
           Total_Area_km2=("Area_km2", "sum")
       )
       .reset_index()
       .sort_values("Total_Area_km2", ascending=False)
)

# Print or export the summary
print(summary)

print("Cleaning geometry to fix topology errors.")
# Clean geometries to fix topology errors
gdf["geometry"] = gdf["geometry"].buffer(0)

print("Dissolving features by RB_Type_L2 to create summary features.")
# Dissolve by RB_Type_L2, keeping only the classification
dissolved = gdf.dissolve(by="RB_Type_L2", as_index=False)[["RB_Type_L2", "geometry"]]

print("Exploding multipart polygons into singlepart polygons.")
# Explode multipart polygons into singlepart polygons
singleparts = dissolved.explode(index_parts=False).reset_index(drop=True)

# Reproject to EPSG:3112 for accurate area calculation (do not overwrite original geometry)
singleparts_proj = singleparts.to_crs(epsg=3112)
singleparts["Area_km2"] = singleparts_proj.geometry.area / 1e6


# Save to shapefile (original CRS)
singleparts.to_file("working/A01/Aus-Trop-Reef-Features_v0-1_RB-Type-L2.shp")

# Summarise by RB_Type_L2: count and total area
summary = (
    singleparts.groupby("RB_Type_L2")
    .agg(
        Feature_Count=("RB_Type_L2", "count"),
        Total_Area_km2=("Area_km2", "sum")
    )
    .reset_index()
    .sort_values("Total_Area_km2", ascending=False)
)

print(summary)
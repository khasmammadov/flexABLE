import pandas as pd

# effElec = 0.7 #electrolyzer efficiency[%]
# effStrg = 0.90 #Storage efficiency[%]
# specEnerCons = 0.005 #System Specific energy consumption per m3 H2 [MWh/Nm3]
# variableCost = 100 #[Euro] cost of producing 1MWh H2 
# energyContentH2_kg = 0.03333 #MWh/kg or 
# energyContentH2_m3 = 0.003 #MWh/Nm³

# Read the CSV file
df = pd.read_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/flexABLE_w_electrolyzer/input/2016/hydrogen_demand_22.csv')

# Get the number of user-inputted rows
num_rows = 35135

# Upsample and converting tonnes H2 values into kg then converting to MWh energy values
upsampled_df = df.sample(num_rows, replace=True) / num_rows * 1000 * 0.06 * 0.25 

print(upsampled_df)

# Save the upsampled dataframe to a CSV file
upsampled_df.to_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/flexABLE_w_electrolyzer/input/2016/hydrogen_demand_upsampled.csv', index=False)

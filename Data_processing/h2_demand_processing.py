import pandas as pd

# Read the CSV file
df = pd.read_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/flexABLE_w_electrolyzer/input/2016/hydrogen_demand_22.csv')

# Get the number of user-inputted rows
num_rows = 35135

# Upsample and converting tonnes H2 values into kg then converting to MWh energy values
upsampled_df = df.sample(num_rows, replace=True) / num_rows * 1000 * 0.06 * 0.25 

print(upsampled_df)

# Save the upsampled dataframe to a CSV file
upsampled_df.to_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/flexABLE_w_electrolyzer/input/2016/hydrogen_demand_upsampled.csv', index=False)

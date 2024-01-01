#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Nov 13 18:17:40 2023

@author: kanan
"""

import pandas as pd
import numpy as np

def upsample_csv(input_path, output_path):
    # Read the original CSV file
    fuelData = pd.read_csv(input_path, index_col=0)

    # Upsample by repeating each row 4 times
    upsampled_data = fuelData.loc[np.repeat(fuelData.index, 4)]

    # Reset the index
    upsampled_data.reset_index(drop=True, inplace=True)

    # Save the upsampled data to a new CSV file
    upsampled_data.to_csv(output_path)

if __name__ == "__main__":
    # Provide the input and output paths
    input_file_path = '/Users/kanan/Library/CloudStorage/OneDrive-Persönlich/Thesis - Electrolyzer market participation/Flexable_electrolyzer/input/2019/weather_CF.csv'  # Update with your actual path
    output_file_path = '/Users/kanan/Library/CloudStorage/OneDrive-Persönlich/Thesis - Electrolyzer market participation/Flexable_electrolyzer/input/2019/weather_CF_upsampled.csv' # Update with your desired output path

    # Call the upsample function
    upsample_csv(input_file_path, output_file_path)

    print("CSV upsampled and saved successfully.")

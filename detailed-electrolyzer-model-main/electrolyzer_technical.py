import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import fsolve


digs = 2  # rounding digits

# Segments
segments = 1

# Input
scenario = pd.read_excel("/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/flexABLE_w_electrolyzer/detailed-electrolyzer-model-main/scenario_data_2019.xlsx")
T = list(range(1, len(scenario) + 1))

# Wind farm
C_W = 104.5  # nominal power wind in MW
CF = scenario['cf']
P_W = CF * C_W  # wind production
lambda_M = scenario['p']  # electricity day ahead market price

# Electrolyzer
C_E = C_W / 2  # size in MW
sb_load = 0.01  # standby load = 1%
P_sb = C_E * sb_load  # standby load = 1%
min_load = 0.15  # minimum load = 15%
P_min = C_E * min_load  # minimum load = 15%
p_cell = 30  # cell pressure bar
T_cell = 90  # cell temperature in celsius
i_max = 5000  # maximum cell current density in A/m2
A_cell = 0.2  # cell area in m2
start_cost = 50  # starting cost of production = 50 EUR/MW
lambda_start = C_E * start_cost  # starting cost of production
eta_full_load = 17.547  # constant production efficiency kg/MWh
TSO_tariff = 15.06  # TSO grid tariff in EUR/MWh
lambda_M_in = scenario['p'] + TSO_tariff  # electricity day ahead market price

# Hydrogen market
lambda_H = 2.10  # EUR per kg

# Hydrogen storage
C_S = C_E * eta_full_load * 24  # max size in kg
soc_0 = 0  # initial storage in MWh

# Compressor
eta_C = 0.75  # mechanical efficiency in %
p_in = 30  # inlet pressure in bar
p_out = 200  # outlet pressure in bar
gamma = 1.4  # adiabatic exponent
T_in = 40 + 273.15  # inlet temperature in K
R = 8.314  # universal gas constant in J/mol*K
M_H2_kg = 2.0159E-03  # molar mass of H2 in kg/mol
P_C = R * T_in / M_H2_kg * gamma / (gamma - 1) * 1 / eta_C * ((p_out / p_in)**((gamma - 1) / gamma) - 1) * 1E-06 / 3600  # compressor consumption in MWh/kg H2

# Daily hours
TT_daily = [list(range((x - 1) * 24 + 1, x * 24 + 1)) for x in range(1, 366)]

# Monthly hours
TT_monthly = [list(range((y - 1) * 24 + 1, y * 24 + 1)) for y in [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]]

# Demand
C_D_daily = C_E * eta_full_load * 4  # in kg per day
C_D_monthly = C_D_daily * 30  # in kg per year
C_D_annual = C_D_daily * 365  # in kg per year

# Set demand style
C_D = C_D_daily
TT = TT_daily

# Coefficients
a1 = 1.5184
a2 = 1.5421E-03
a3 = 9.523E-05
a4 = 9.84E-08
r1 = 4.45153E-05
r2 = 6.88874E-09
d1 = -3.12996E-06
d2 = 4.47137E-07
s = 0.33824
t1 = -0.01539
t2 = 2.00181
t3 = 15.24178
B1 = 4.50E-05
B2 = 1.02116
B3 = -247.26
B4 = 2.06972
B5 = -0.03571
f11 = 478645.74
f12 = -2953.15
f21 = 1.0396
f22 = -0.00104
F_const = 96485.3321
M_H2 = 2.0159  # molar mass of H2 in kg/mol
HHV = 39.41

#%%
# Functions from find current file
def U_rev(temp):
    T = temp + 273.15
    U_rev = a1 - a2 * T + a3 * T * np.log(T) + a4 * T**2
    return U_rev

def find_i_from_p(p_val, C_E, n_cell, A_cell, T, p):
    i_pval = np.zeros(len(p_val))
    for j in range(len(p_val)):
        P_j = p_val[j] * C_E * 10**6
        def f(x):
            return (U_rev(T) + (r1 + d1 + r2 * T + d2 * p) * x + s * np.log10((t1 + t2 / T + t3 / T**2) * x + 1)) * x * n_cell * A_cell - P_j
        i_pval[j] = fsolve(f, [2000])
    return i_pval
#%%
#Functions from input.jl file
# Reversible cell voltage
def U_rev(Temp):
    Temp_K = Temp + 273.15
    U_rev = a1 - a2 * Temp_K + a3 * Temp_K * np.log(Temp_K) + a4 * Temp_K**2
    return U_rev

# Real cell voltage
def U_cell(Temp, p, i):
    U_cell = U_rev(Temp) + ((r1 + d1) + r2 * Temp + d2 * p) * i + s * np.log10((t1 + t2 / Temp + t3 / Temp**2) * i + 1)
    return U_cell

# Cell power consumption
def P_cell(Temp, p, i):
    P_cell = i * U_cell(Temp, p, i)
    return P_cell

# Faraday efficiency (5-parameter)
def eta_F_5(Temp, i):
    eta_F = B1 + B2 * np.exp((B3 + B4 * Temp + B5 * Temp**2) / i)
    return eta_F

# Faraday efficiency
def eta_F(Temp, i):
    eta_F = (i**2 / (f11 + f12 * Temp + i**2)) * (f21 + f22 * Temp)
    return eta_F

# Cell production
def M_H_cell(Temp, i):
    M_H_cell = (eta_F(Temp, i) * M_H2 * i) / (2 * F_const)
    M_H_cell_kg_h = M_H_cell * 3.6
    return M_H_cell_kg_h

# System production
def M_H_sys(Temp, i, I, n_c):
    M_H_cell = (eta_F(Temp, i) * n_c * M_H2 * I) / (2 * F_const)
    M_H_cell_kg_h = M_H_cell * 3.6
    return M_H_cell_kg_h

# Cell efficiency
def eta_cell(Temp, p, i):
    eta_cell = M_H_cell(Temp, i) * HHV / P_cell(Temp, p, i)
    return eta_cell

# Number of cells
def n_cell(i_max, A_cell, C_E, Temp, p):
    I_max_cell = i_max * A_cell
    U_max_cell = U_cell(Temp, p, i_max)
    P_max_cell = I_max_cell * U_max_cell
    n_cell = (C_E * 1000000) / P_max_cell
    return n_cell

# Production curve
def P_curve(P_list, S, i_max, A_cell, C_E, Temp, p):
    N = list(range(len(P_list)))
    a = []
    b = []
    n_x = []
    n_y = []
    n_c = n_cell(i_max, A_cell, C_E, Temp, p)
    i_list = np.array([find_i_from_p(P, C_E, n_c, A_cell, Temp, p) for P in P_list])

    for n in N:
        i = i_list[n]
        I = i_list[n] * A_cell
        U = U_cell(Temp, p, i) * n_c
        P = I * U / 1000000
        M = M_H_sys(Temp, i, I, n_c)
        n_x.append(P)
        n_y.append(M)
    for s in S:  # a and b for segment
        a_s = (n_y[s] - n_y[s + 1]) / (n_x[s] - n_x[s + 1])
        b_s = n_y[s] - (a_s * n_x[s])
        a.append(a_s)
        b.append(b_s)

    return a, b, n_x, n_y

# Production curve
P_E_min = min_load  # minimum load for production
P_E_opt = 0.28231501
P_E_max = 1
P_segments = [
    [P_E_min, P_E_max],  # Segment 1
    [P_E_min, P_E_opt, P_E_max],  # Segment 2
    [],  # Segment 3
    [P_E_min, (P_E_min + P_E_opt) / 2, P_E_opt, (P_E_opt + P_E_max) / 2, P_E_max],  # Segment 4
    [],  # Segment 5
    [],  # Segment 6
    [],  # Segment 7
    [P_E_min, (P_E_min + (P_E_min + P_E_opt) / 2) / 2, (P_E_min + P_E_opt) / 2, ((P_E_min + P_E_opt) / 2 + P_E_opt) / 2, P_E_opt,
    (P_E_opt + (P_E_opt + P_E_max) / 2) / 2, (P_E_opt + P_E_max) / 2, ((P_E_opt + P_E_max) / 2 + P_E_max) / 2, P_E_max],  # Segment 8
    [],  # Segment 9
    [],  # Segment 10
    [],  # Segment 11
    [P_E_min, (P_E_min + (P_E_min + P_E_opt) / 2) / 2, (P_E_min + P_E_opt) / 2, ((P_E_min + P_E_opt) / 2 + P_E_opt) / 2, P_E_opt,
     (P_E_opt + (P_E_opt + (P_E_opt + P_E_max) / 2) / 2) / 2, (P_E_opt + (P_E_opt + P_E_max) / 2) / 2,
     ((P_E_opt + (P_E_opt + P_E_max) / 2) / 2 + (P_E_opt + P_E_max) / 2) / 2, (P_E_opt + P_E_max) / 2,
     ((P_E_opt + P_E_max) / 2 + ((P_E_opt + P_E_max) / 2 + P_E_max) / 2) / 2, ((P_E_opt + P_E_max) / 2 + P_E_max) / 2,
     (((P_E_opt + P_E_max) / 2 + P_E_max) / 2 + P_E_max) / 2, P_E_max]  # Segment 12
]
P_list = P_segments[segments]
S = list(range(1, len(P_list) - 1))
curve = P_curve(P_list, S, i_max, A_cell, C_E, T_cell, p_cell)
a = curve[0]
b = curve[1]

# Non-linear plot
n_c = n_cell(i_max, A_cell, C_E, T_cell, p_cell)
df = pd.DataFrame({'i': list(range(1, i_max+1)), 'u': np.zeros(i_max), 'eta_F': np.zeros(i_max), 'load': np.zeros(i_max), 'power': np.zeros(i_max), 'prod': np.zeros(i_max), 'eff': np.zeros(i_max)})
for i in df['i']:
    I = i * A_cell
    df.at[i-1, 'u'] = U_cell(T_cell, p_cell, i)
    df.at[i-1, 'eta_F'] = eta_F(T_cell, i)
    df.at[i-1, 'power'] = i * A_cell * df.at[i-1, 'u'] * n_c / 1000000
    df.at[i-1, 'load'] = df.at[i-1, 'power'] / C_E
    df.at[i-1, 'prod'] = M_H_sys(T_cell, i, I, n_c)
    df.at[i-1, 'eff'] = df.at[i-1, 'prod'] / df.at[i-1, 'power']

# Plotting
plt.figure(figsize=(10, 6))
plt.plot(df['power'], df['prod'], label="Curve", linewidth=4, color='red')
plt.plot(curve[2], curve[3], label="Segments", linewidth=3, color='blue')
plt.xlabel('Consumption [MWh]')
plt.ylabel('Production [kg]')
plt.title('Production Curve')
plt.xticks(np.arange(3, 21, step=2))
plt.yticks(np.arange(0, 351, step=25))
plt.legend(loc='lower right')
plt.grid(True)
plt.show()
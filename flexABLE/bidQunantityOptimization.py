import pandas as pd 
import pyomo.environ as pyomo
from pyomo.opt import SolverFactory 

foresight = 96 #timesteps for a day 4*24
installedCapacity = 100
# mode = 'regular_production'
mode =  input("Choose optimization mode, 1 for regular production 2 for flexible production: ")
# #%%
# effElec = 0.7 #electrolyzer efficiency[%]
# effStrg = 0.90 #Storage efficiency[%]
# specEnerCons = 0.005 #System Specific energy consumption per m3 H2 [MWh/Nm3]
# maxSOC = 1000 #[m3] storage capacity of H2 that can be stored
# variableCost = 100 #[Euro] cost of producing 1MWh H2 
# energyContentH2_kg = 0.03333 #MWh/kg or 
# energyContentH2_m3 = 0.003 #MWh/Nm³
# dt = 0.25 

industrialDemandH2 = pd.read_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/Flexable_industrial_h2_optimization/input/2016/industrial_demand.csv') 
PFC = pd.read_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/Flexable_industrial_h2_optimization/input/2016/PFC_run1.csv')
industrialDemandH2 = industrialDemandH2[0:672]
PFC = PFC[0:672]
# Convert DataFrame columns to lists 
price = PFC['price'].tolist()
industry_demand = industrialDemandH2['industry'].tolist()

# Calculate the maxSOC 
demand_intervals = len(industry_demand) // foresight
interval_sums = [sum(industry_demand[i:i+foresight]) for i in range(0, len(industry_demand), foresight)]
maxSOC = max(interval_sums)

def optimizeH2Prod(price, industry_demand, mode):
    model = pyomo.ConcreteModel()
    model.i = pyomo.RangeSet(0, len(price) - 1)

    # Define the decision variables
    model.bidQuantity = pyomo.Var(model.i, domain=pyomo.NonNegativeReals)
    model.SOC = pyomo.Var(model.i)

    # Define the objective function
    model.obj = pyomo.Objective(expr=sum(price[i] * model.bidQuantity[i] for i in model.i), sense=pyomo.minimize)
    
    # Define SOC constraints
    if mode == '1':
        model.currentSOC = pyomo.Constraint(model.i, rule=lambda model, i:
                                            model.SOC[i] == model.SOC[i - 1] + model.bidQuantity[i] - industry_demand[i]
        
                                            if i > 0 else model.SOC[i] == model.bidQuantity[i] - industry_demand[i])   #for initial timestep at each optimization cycle
        model.maxSOC = pyomo.Constraint(model.i, rule=lambda model, i: model.SOC[i] <= maxSOC)

    elif mode == '2':
        model.currentSOC = pyomo.Constraint(model.i, rule=lambda model, i:
                                            model.SOC[i] == model.SOC[i - 1] + model.bidQuantity[i] - industry_demand[i]
                                            if i > 0 else model.SOC[0] >= industry_demand[0])   #for initial timestep at each optimization cycle
        model.totalDemand = pyomo.Constraint(expr=sum(model.bidQuantity[i] for i in model.i) == sum(industry_demand[i] for i in model.i)) #clarify unit, power/energy conversation

    # Demand should be covered at each step 
    model.demand_i = pyomo.Constraint(model.i, rule=lambda model, i: model.SOC[i] >= industry_demand[i])
    # model.totalDemand = pyomo.Constraint(expr=sum(model.bidQuantity[i] for i in model.i) == sum(industry_demand[i] for i in model.i)) #clarify unit, power/energy conversation

    # Max installed capacity constraint 
    model.maxPower = pyomo.Constraint(model.i, rule=lambda model, i: model.bidQuantity[i] <= installedCapacity)
    
    # Solve the optimization problem
    opt = SolverFactory("gurobi")  # You can replace this with your preferred solver
    result = opt.solve(model)

    print(result.solver.status)
    print(result.solver.termination_condition)

    # Retrieve the optimal values
    optimalBidamount = [model.bidQuantity[i].value for i in model.i]
    currentSOC = [model.SOC[i].value for i in model.i]
    
    return optimalBidamount, currentSOC

# Create lists to store results
allBidQuantity = []
allCurrentSOC = []

# Assuming  data has 96 timesteps for each day
price_intervals = len(price) // foresight

for interval in range(price_intervals):
    # Extract data for the current time interval
    start_idx = interval * foresight #start point for time interval
    end_idx = (interval + 1) * foresight #start point for time interval
    interval_industrial_demand = list(industry_demand[start_idx:end_idx])
    interval_PFC = price[start_idx:end_idx]

    # Perform optimization for the current interval
    optimalBidamount, currentSOC = optimizeH2Prod(price=interval_PFC, industry_demand=interval_industrial_demand, mode=mode)

    # Append results to the lists
    allBidQuantity.extend(optimalBidamount)
    allCurrentSOC.extend(currentSOC)


# Export variables to CSV file
data = {'industry_demand': industry_demand, 'allBidQuantity': allBidQuantity, 'allCurrentSOC': allCurrentSOC, 'price': price}
df = pd.DataFrame(data)
if mode == '1':
    df.to_csv('Data_processing/optimizedBidAmount_regular_prod.csv', index=False)
elif mode == '2':        
    df.to_csv('Data_processing/optimizedBidAmount_flexible_prod.csv', index=False)


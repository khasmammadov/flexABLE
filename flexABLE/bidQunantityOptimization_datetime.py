import pandas as pd 
import pyomo.environ as pyomo
from pyomo.opt import SolverFactory 

installedCapacity = 100
# effElec = 0.7 #electrolyzer efficiency[%]
# effStrg = 0.90 #Storage efficiency[%]
# specEnerCons = 0.005 #System Specific energy consumption per m3 H2 [MWh/Nm3]
# variableCost = 100 #[Euro] cost of producing 1MWh H2 
# energyContentH2_kg = 0.03333 #MWh/kg or 
# energyContentH2_m3 = 0.003 #MWh/Nm³

industrialDemandH2 = pd.read_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/flexABLE_w_electrolyzer/input/2016/industrial_demand.csv') 
PFC = pd.read_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/flexABLE_w_electrolyzer/input/2016/PFC_run1.csv')

# Convert DataFrame columns to lists 
# price = PFC['price'].tolist()
# industry_demand = industrialDemandH2['industry'].tolist()

#specify optimization function
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

    # Max installed capacity constraint 
    model.maxPower = pyomo.Constraint(model.i, rule=lambda model, i: model.bidQuantity[i] <= installedCapacity)
    
    # Solve the optimization problem
    opt = SolverFactory("gurobi")  # You can replace this with your preferred solver
    result = opt.solve(model)

    print('Solver status:', result.solver.status)
    print('Termination condition: ', result.solver.termination_condition)

    # Retrieve the optimal values
    optimalBidamount = [model.bidQuantity[i].value for i in model.i]
    currentSOC = [model.SOC[i].value for i in model.i]
    return optimalBidamount, currentSOC

#set up user input variables
desired_year = 2016 #will get from scenarios 
mode = input("Choose optimization mode, 1 for regular production 2 for flexible production: ")
optTimeframe = input("Choose optimization timefrme, day or week : ")

#adding timestamp to input data
industrialDemandH2['Timestamp'] = pd.date_range(start=f'1/1/{desired_year}', end=f'12/31/{desired_year} 23:45', freq='15T')
PFC['Timestamp'] = pd.date_range(start=f'1/1/{desired_year}', end=f'12/31/{desired_year} 23:45', freq='15T')

# Calculate the maxSOC 
demandSum = [] #weekly or daily demand sum
if optTimeframe == "week":
    # Use isocalendar to get the week number
    industrialDemandH2['Week'] = industrialDemandH2['Timestamp'].dt.isocalendar().week
    unique_weeks = industrialDemandH2['Week'].unique()
    for week in unique_weeks:
        weeklyIntervalDemand = industrialDemandH2[industrialDemandH2['Week'] == week]
        weekly_sum = sum(weeklyIntervalDemand['industry'])
        demandSum.append(weekly_sum)
elif optTimeframe == "day":
    # Use dt.date to get the date
    industrialDemandH2['Date'] = industrialDemandH2['Timestamp'].dt.date
    unique_days = industrialDemandH2['Date'].unique()
    for day in unique_days:
        dailyIntervalDemand = industrialDemandH2[industrialDemandH2['Date'] == day]
        daily_sum = sum(dailyIntervalDemand['industry'])
        demandSum.append(daily_sum)        
maxSOC = max(demandSum)

# Create lists to store results
allBidQuantity = []
allCurrentSOC = []

#setting optimization modes and calling optimization function
if optTimeframe == "week":
    # Use isocalendar to get the week number
    industrialDemandH2['Week'] = industrialDemandH2['Timestamp'].dt.isocalendar().week
    PFC['Week'] = PFC['Timestamp'].dt.isocalendar().week
    unique_weeks = industrialDemandH2['Week'].unique()
    for week in unique_weeks:
        # Extract data for the current week
        weeklyIntervalDemand = industrialDemandH2[industrialDemandH2['Week'] == week]
        weeklyIntervalDemand = list(weeklyIntervalDemand['industry'])
        weeklyIntervalPFC = PFC[PFC['Week'] == week]
        weeklyIntervalPFC = list(weeklyIntervalPFC['price'])
        optimalBidamount, currentSOC = optimizeH2Prod(price=weeklyIntervalPFC, industry_demand=weeklyIntervalDemand, mode=mode)
        allBidQuantity.extend(optimalBidamount)
        allCurrentSOC.extend(currentSOC)
elif optTimeframe == "day":
    # Use dt.date to get the date
    industrialDemandH2['Date'] = industrialDemandH2['Timestamp'].dt.date
    PFC['Date'] = PFC['Timestamp'].dt.date
    # Determine the unique dates in the year
    unique_days = industrialDemandH2['Date'].unique()
    for day in unique_days:
        # Extract data for the current date
        dailyIntervalDemand = industrialDemandH2[industrialDemandH2['Date'] == day]
        dailyIntervalDemand = list(dailyIntervalDemand['industry'])
        dailyIntervalPFC = PFC[PFC['Date'] == day]
        dailyIntervalPFC = list(dailyIntervalPFC['price'])
        # Continue with the optimization for the current daste
        optimalBidamount, currentSOC = optimizeH2Prod(price=dailyIntervalPFC, industry_demand=dailyIntervalDemand, mode=mode)
        allBidQuantity.extend(optimalBidamount)
        allCurrentSOC.extend(currentSOC)        

# Export variables to CSV file
data = {'industry_demand': industry_demand, 'allBidQuantity': allBidQuantity, 'allCurrentSOC': allCurrentSOC, 'price': price}
df = pd.DataFrame(data)
df.to_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/flexABLE_w_electrolyzer/Data_processing/optimizedBidAmount.csv', index=False)


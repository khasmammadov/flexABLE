#%%
import pandas as pd 
import pyomo.environ as pyomo
from pyomo.opt import SolverFactory 

#Electrolyzer Parameters
maxPower = 300 #MW
minPower = 10 #[MW]
effElec = 0.4 #electrolyzer efficiency[%]
pressElec = 30 #pressure of H2 at the end of electrolyzer [bar]
# specEnerCons = 0.005 #System Specific energy consumption per m3 H2 [MWh/Nm3]

energyContentH2_LHV = 0.03333 #MWh/kg or lower heating value
energyContentH2_HHV = 0.03939 #MWh/kg or higher heating value
#energyContentH2_m3 = 0.003 #MWh/Nm³

#elect Status parameters
minRuntime = 5
minDowntime = 2 #hours
shutDownafterInactivity = 4 #hours
startUpCost = 50 #50 euro per installed capacity[MW]
standbyCons = 0.2 #[MW]
maxAllowedColdStartups = 1  #3000-5000/year


#Compressor
# specComprCons = 0.0012 #specific compressor consumption [MWh/kg]
compEff = 0.75 # mechanical efficiency in %
compPressIn = 30 # inlet pressure in bar
compPressOut = 300 # outlet pressure in bar
gamma = 1.4 # adiabatic exponent
compTempIn = 40 + 273.15 # inlet temperature in K
R = 8.314 # universal gas constant in J/mol*K
M_H2_kg = 2.0159E-03 # molar mass of H2 in kg/mol
compCons = R * compTempIn / M_H2_kg * gamma / (gamma-1) * 1 / compEff * ((compPressOut/compPressIn)**((gamma-1)/gamma)-1) * 1E-06 / 3600 # compressor consumption in MWh/kg H2

#storage parameters
maxSOC = 4000 #kilo of H2 
storageFlowOutput = 200 #kg/hr
# storageVolume = 159000 #liter
# storageTemp  = 293 #storage temperature Kelvin
# storagePress = 31 #bar
# pressureDiff = storagePress - pressElec #bar
# maxSOC_kg = pressureDiff * storageVolume * 2.0159 /1.05/8.3145/storageTemp/1000  #molarMass/meanRealGasFactor/universalGasConst
# print(maxSOC_kg, 'maxSOC_kg')
industrialDemandH2 = pd.read_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/flexABLE_w_electrolyzer/input/2016/industrial_demand.csv')  #should be in kilos 
PFC = pd.read_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/flexABLE_w_electrolyzer/output/PFC_export.csv')
industrialDemandH2 = industrialDemandH2[0:288]
PFC = PFC[0:288]

# Convert DataFrame columns to lists 
price = PFC['PFC'].tolist()
industry_demand = industrialDemandH2['Elec_x'].tolist()


#%%
#specify optimization function
def optimizeH2Prod(price, industry_demand, time_periods):
    model = pyomo.ConcreteModel('Optimized Electroluzer Bidding')
    model.i = pyomo.RangeSet(0, len(price) - 1)
    model.bidQuantity_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals)
    model.prodH2_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #produced H2
    model.elecCons_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #electrolyzer consumption per kg
    model.elecstartUpCost_EUR = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #electrolyzer startup consumption
    model.comprCons_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #compressor consumption per kg
    model.elecToStorage_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #H2 from electrolyzer to storage
    model.elecToPlantUse_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #H2 from electrolyzer to process
    model.storageToPlantUse_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #H2 from storage to process
    model.currentSOC_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #Status of Storage

    # Binary variable to represent the status of the electrolyzer (on/off)
    model.isRunning = pyomo.Var(model.i, domain=pyomo.Binary, doc='Electrolyzer running')
    model.isStarted = pyomo.Var(model.i, domain=pyomo.Binary, doc='Electrolyzer started')
    
    # Define the objective function
    model.obj = pyomo.Objective(expr=sum(price[i] * model.bidQuantity_MW[i] + model.elecstartUpCost_EUR[i] for i in model.i), sense=pyomo.minimize)

    # Status constraints and constraining max and min bid quantity 
    model.maxPower_rule = pyomo.Constraint(model.i, rule=lambda model, i:
                                            model.elecCons_MW[i] <= maxPower * model.isRunning[i])

    model.minPower_rule = pyomo.Constraint(model.i, rule=lambda model, i:
                                            model.elecCons_MW[i] >= minPower * model.isRunning[i])

    def electrolyzerStarted(model, i):
        if i == 0:
            return pyomo.Constraint.Skip
        else:
            return model.isRunning[i]<= model.isRunning[i-1] + model.isStarted[i]
    model.electrolyzerStarted = pyomo.Constraint(model.i, rule=electrolyzerStarted)    
    
    def minRuntime_rule(model, i):
        next_time_periods = {i + offset for offset in range(minRuntime) if i + offset < time_periods}
        return sum(model.isRunning[tt] for tt in next_time_periods) >= len(next_time_periods) * model.isStarted[i]
    model.minRuntime_rule = pyomo.Constraint(model.i, rule=minRuntime_rule)       

    def minDownTime_rule(model, i):
        if i == 0:
            return pyomo.Constraint.Skip
        previous_time_periods = {i - offset for offset in range(1, minDowntime + 1) if i - offset >=0}
        return len(previous_time_periods) * model.isStarted[i] <= sum(1-model.isRunning[tt] for tt in previous_time_periods)
    model.minDownTime_rule = pyomo.Constraint(model.i, rule=minDownTime_rule) 
    
    model.maxColdStartup_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                        sum(model.isStarted[i] for i in range(0, time_periods)) <= maxAllowedColdStartups)          

    model.totalProducedH2 = pyomo.Constraint(model.i, rule=lambda model, i: 
                                        model.elecCons_MW[i] ==  model.prodH2_kg[i] / 0.25 / effElec * energyContentH2_LHV)
    #hydrogen balance
    model.producedH2allocation_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                            model.prodH2_kg[i] == model.elecToPlantUse_kg[i] + model.elecToStorage_kg[i])   
    #demand balance
    model.producedH2allocation_rule2 = pyomo.Constraint(model.i, rule=lambda model, i: 
                                            industry_demand[i] == model.elecToPlantUse_kg[i] + model.storageToPlantUse_kg[i])   
        
    model.compressorConsumption_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                model.comprCons_MW[i] == model.elecToStorage_kg[i] * compCons)

    model.elecStartupCost_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                model.elecstartUpCost_EUR[i] == startUpCost * model.isStarted[i])
    
    model.storageFlowRate_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                            model.storageToPlantUse_kg[i] <= storageFlowOutput)  

    model.electricalBalance_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                            model.bidQuantity_MW[i] == model.elecCons_MW[i] +  model.comprCons_MW[i]) 
    
    # Define Storage constraint
    model.currentSOC_rule = pyomo.Constraint(model.i, rule=lambda model, i:
                                        model.currentSOC_kg[i] == model.currentSOC_kg[i - 1] + model.elecToStorage_kg[i] - model.storageToPlantUse_kg[i]
                                        if i > 0 else model.currentSOC_kg[i] == model.elecToStorage_kg[i]  - model.storageToPlantUse_kg[i])  
    
    model.maxSOC_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                        model.currentSOC_kg[i] <= maxSOC)
    
  # Solve the optimization problem
    opt = SolverFactory("gurobi")  # You can replace this with your preferred solver
    result = opt.solve(model, tee=True)

    print('Solver status:', result.solver.status)
    print('Termination condition: ', result.solver.termination_condition)
    
    # Retrieve the optimal values
    optimalBidamount = [model.bidQuantity_MW[i].value for i in model.i]
    elecCons = [model.elecCons_MW[i].value for i in model.i]
    elecStartUpCost = [model.elecstartUpCost_EUR[i].value for i in model.i]         
    comprCons = [model.comprCons_MW[i].value for i in model.i]
    prodH2 = [ model.prodH2_kg[i].value for i in model.i]           
    elecToPlantUse_kg = [ model.elecToPlantUse_kg[i].value for i in model.i]            
    elecToStorage_kg = [ model.elecToStorage_kg[i].value for i in model.i]            
    storageToPlantUse_kg = [ model.storageToPlantUse_kg[i].value for i in model.i]            
    currentSOC = [model.currentSOC_kg[i].value for i in model.i]                
    isRunning =   [model.isRunning[i].value for i in model.i]
    isStarted = [model.isStarted[i].value for i in model.i]
    return optimalBidamount,elecCons, elecStartUpCost, comprCons, prodH2, elecToPlantUse_kg, elecToStorage_kg, storageToPlantUse_kg, currentSOC, isRunning, isStarted

#set up user input variables
desired_year = 2016 #will get from scenarios 
optTimeframe = 'day' #input("Choose optimization timefrme, day or week : ")

#adding timestamp to input data
industrialDemandH2['Timestamp'] = pd.date_range(start=f'1/1/{desired_year}', end=f'1/3/{desired_year} 23:45', freq='15T')
PFC['Timestamp'] = pd.date_range(start=f'1/1/{desired_year}', end=f'1/3/{desired_year} 23:45', freq='15T')

#%% maxSOC calculation
# # Calculate the maxSOC 
# demandSum = [] #weekly or daily demand sum
# if optTimeframe == "week":
#     # Use isocalendar to get the week number
#     industrialDemandH2['Week'] = industrialDemandH2['Timestamp'].dt.isocalendar().week
#     unique_weeks = industrialDemandH2['Week'].unique()
#     for week in unique_weeks:
#         weeklyIntervalDemand = industrialDemandH2[industrialDemandH2['Week'] == week]
#         weekly_sum = sum(weeklyIntervalDemand['industry'])
#         demandSum.append(weekly_sum)
# elif optTimeframe == "day":
#     # Use dt.date to get the date
#     industrialDemandH2['Date'] = industrialDemandH2['Timestamp'].dt.date
#     unique_days = industrialDemandH2['Date'].unique()
#     for day in unique_days:
#         dailyIntervalDemand = industrialDemandH2[industrialDemandH2['Date'] == day]
#         daily_sum = sum(dailyIntervalDemand['industry'])
#         demandSum.append(daily_sum)        
# maxSOC = max(demandSum)
#%%  Running interval simulation
# Create lists to store results

allBidQuantity = []
allelecCons = []
allelecStartUpCost = []
allcomprCons = []
allprodH2 = []
allelecToPlantUse_kg = []
allelecToStorage_kg = []
allstorageToPlantUse_kg = []
allCurrentSOC = []
all_isRunning = []
all_isStarted = []

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
        weeklyIntervalPFC = list(weeklyIntervalPFC['PFC'])
        time_periods = len(weeklyIntervalPFC)  
        optimalBidamount,elecCons,  comprCons, prodH2, elecToPlantUse_kg, elecToStorage_kg, storageToPlantUse_kg, currentSOC, isRunning = optimizeH2Prod(price=weeklyIntervalPFC, industry_demand=weeklyIntervalDemand, time_periods=time_periods)   
        allBidQuantity.extend(optimalBidamount)
        allelecCons.extend(elecCons)
        allcomprCons.extend(comprCons)
        allprodH2.extend(prodH2)
        allelecToPlantUse_kg.extend(elecToPlantUse_kg)
        allelecToStorage_kg.extend(elecToStorage_kg)
        allstorageToPlantUse_kg.extend(storageToPlantUse_kg)
        allCurrentSOC.extend(currentSOC)
        all_isRunning.extend(isRunning) 
elif optTimeframe == "day":
    industrialDemandH2['Date'] = industrialDemandH2['Timestamp'].dt.date
    PFC['Date'] = PFC['Timestamp'].dt.date
    # Determine the unique dates in the year
    unique_days = industrialDemandH2['Date'].unique()
    for day in unique_days:
        # Extract data for the current date
        dailyIntervalDemand = industrialDemandH2[industrialDemandH2['Date'] == day]
        dailyIntervalDemand = list(dailyIntervalDemand['Elec_x'])
        dailyIntervalPFC = PFC[PFC['Date'] == day]
        dailyIntervalPFC = list(dailyIntervalPFC['PFC'])
        time_periods = len(dailyIntervalPFC)
        # Continue with the optimization for the current daste
        optimalBidamount,elecCons, elecStartUpCost, comprCons, prodH2, elecToPlantUse_kg, elecToStorage_kg, storageToPlantUse_kg, currentSOC, isRunning, isStarted = optimizeH2Prod(price=dailyIntervalPFC, industry_demand=dailyIntervalDemand,time_periods = time_periods)   
        allBidQuantity.extend([round(item, 3) for item in optimalBidamount])
        allelecCons.extend([round(item, 3) for item in elecCons])
        allelecStartUpCost.extend([round(item, 3) for item in elecStartUpCost])        
        allcomprCons.extend([round(item, 3) for item in comprCons])
        allprodH2.extend([round(item, 3) for item in prodH2])
        allelecToPlantUse_kg.extend([round(item, 3) for item in elecToPlantUse_kg])
        allelecToStorage_kg.extend([round(item, 3) for item in elecToStorage_kg])
        allstorageToPlantUse_kg.extend([round(item, 3) for item in storageToPlantUse_kg])
        allCurrentSOC.extend([round(item, 3) for item in currentSOC])
        all_isRunning.extend(isRunning)        
        all_isStarted.extend(isStarted)        


# Export variables to CSV file
data = {'industry_demand': industry_demand, 
        'optimalBidamount': allBidQuantity,
        'elecCons': allelecCons,
        'elecStartUpCost': allelecStartUpCost,
        'comprCons': allcomprCons, 
        'prodH2': allprodH2,
        'elecToPlantUse_kg':allelecToPlantUse_kg,
        'elecToStorage_kg':allelecToStorage_kg,
        'storageToPlantUse_kg':allstorageToPlantUse_kg, 
        'currentSOC': allCurrentSOC, 
        'price': price, 
        'isRunning':all_isRunning,
        'isStarted': all_isStarted}
df = pd.DataFrame(data)
df.to_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/flexABLE_w_electrolyzer/Data_processing/optimizedBidAmount.csv', index=True)



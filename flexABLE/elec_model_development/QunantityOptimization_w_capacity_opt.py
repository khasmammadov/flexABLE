#%%
import pandas as pd 
import pyomo.environ as pyomo
from pyomo.opt import SolverFactory 

#Electrolyzer Parameters
installedCapacity = 500 #MW
minPower = 10 #[MW]
effElec = 0.7 #average electrolyzer efficiency[%]
pressElec = 30 #pressure of H2 at the end of electrolyzer [bar]
investmentCost_elec = 1078000 #Euro/MW
investmentCost_storage = 530 #Euro/kg

energyContentH2_LHV = 0.03333 #MWh/kg or lower heating value
energyContentH2_HHV = 0.03939 #MWh/kg or higher heating value
maxAllowedColdStartups = 30

#elect Status parameters
minRuntime = 5
minDowntime = 3 #hours
standbyCons = installedCapacity*0.01*0.25 #1% of capacity[MW]
elecHotStartUpCons = installedCapacity*0.005*0.25
elecColdStartUpCons = installedCapacity*0.05*0.25
#Compressor
# specComprCons = 0.0012 #specific compressor consumption [MWh/kg]
compEff = 0.75 # mechanical efficiency in %
compPressIn = 30 # inlet pressure in bar
compPressOut = 300 # outlet pressure in bar
compTempIn = 40 # inlet temperature in K

def compressorConsumtion(compEff, compPressIn, compPressOut, compTempIn):
    gamma = 1.4 # adiabatic exponent
    inlet_temperature = compTempIn + 273.15 # inlet temperature in K
    R = 8.314 # universal gas constant in J/mol*K
    M_H2_kg = 2.0159E-03 # molar mass of H2 in kg/mol
    compCons = R * inlet_temperature / M_H2_kg * gamma / (gamma-1) * 1 / compEff * ((compPressOut/compPressIn)**((gamma-1)/gamma)-1) * 1E-06 / 3600 # compressor consumption in MWh/kg H2
    return compCons

compCons = compressorConsumtion(compEff=compEff, compPressIn=compPressIn, compPressOut=compPressOut, compTempIn=compTempIn)


#%%
#storage parameters
# maxSOC = 10000 #kilo of H2
# storageFlowOutput = 300 #kg/hr
# storageVolume = 159000 #liter
# storageTemp  = 293 #storage temperature Kelvin
# storagePress = 31 #bar
# pressureDiff = storagePress - pressElec #bar
# maxSOC_kg = pressureDiff * storageVolume * 2.0159 /1.05/8.3145/storageTemp/1000  #molarMass/meanRealGasFactor/universalGasConst
# print(maxSOC_kg, 'maxSOC_kg')

industrialDemandH2 = pd.read_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/flexABLE_w_electrolyzer/Data_processing/Metallerzeugung.csv')  #should be in kilos 
PFC = pd.read_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/flexABLE_w_electrolyzer/input/2016/PFC_run1.csv')
industrialDemandH2 = industrialDemandH2['H2_demand_metal'][0:2688]
PFC = PFC[0:2688]

# Convert DataFrame columns to lists 
price = PFC['price'].tolist()
industry_demand = industrialDemandH2.tolist()


#%%
#specify optimization function
def optimizeH2Prod(price, industry_demand, time_periods):
    model = pyomo.ConcreteModel('Optimized Electroluzer Bidding')
    model.i = pyomo.RangeSet(0, len(price) - 1)
    
    # Define the decision variables
    # model.totalInvestment = pyomo.Var(domain=pyomo.NonNegativeReals)
    model.elecCapacity = pyomo.Var(domain=pyomo.NonNegativeReals)
    model.storageCapacity = pyomo.Var(domain=pyomo.NonNegativeReals)    
    model.bidQuantity_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals)
    model.prodH2_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #produced H2
    model.elecCons_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #electrolyzer consumption per kg
    model.elecStandByCons_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #electrolyzer consumption per kg
    model.elecColdStartUpCons_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #electrolyzer consumption per kg
    model.elecHotStartUpCons_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #electrolyzer consumption per kg
    model.comprCons_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #compressor consumption per kg
    model.elecToStorage_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #H2 from electrolyzer to storage
    model.elecToPlantUse_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #H2 from electrolyzer to process
    model.storageToPlantUse_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #H2 from storage to process
    model.currentSOC_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #Status of Storage

    # Binary variable to represent the status of the electrolyzer (on/off)
    model.isRunning = pyomo.Var(model.i, domain=pyomo.Binary, doc='Electrolyzer running')
    model.isColdStarted = pyomo.Var(model.i, domain=pyomo.Binary, doc='Electrolyzer  start from idle')
    model.isHotStarted = pyomo.Var(model.i, domain=pyomo.Binary, doc='Electrolyzer  start from standby')
    model.isIdle = pyomo.Var(model.i, domain=pyomo.Binary, doc='Electrolyzer is idle')
    model.isStandBy = pyomo.Var(model.i, domain=pyomo.Binary, doc='Electrolyzer isStandBy')

    # Define the objective function
    model.obj = pyomo.Objective(expr=investmentCost_elec * model.elecCapacity + investmentCost_storage*model.storageCapacity + sum(price[i]*model.bidQuantity_MW[i] for i in model.i), sense=pyomo.minimize)

    #Max power boundary
    model.maxPower_rule = pyomo.Constraint(model.i, rule=lambda model, i:
                                            model.elecCons_MW[i] <= model.elecCapacity * model.isRunning[i] + 0.01*0.25*model.elecCapacity*model.isStandBy[i] )
    #min power boundary
    model.minPower_rule = pyomo.Constraint(model.i, rule=lambda model, i: #minimum power is 10% of installed capacity
                                            model.elecCons_MW[i] >= 0.1 * model.elecCapacity * model.isRunning[i]+ 0.01*0.25*model.elecCapacity*model.isStandBy[i])
    #only one operational mode
    model.statesExclusivity = pyomo.Constraint(model.i, rule=lambda model, i:
                                            model.isRunning[i] + model.isIdle[i] + model.isStandBy[i] == 1)
    #transition from off to on state
    model.statesExclusivity_2 = pyomo.Constraint(model.i, rule=lambda model, i:
                                            model.isColdStarted[i] >= model.isRunning[i] - model.isRunning[i-1]- model.isStandBy[i-1] if i > 0 else pyomo.Constraint.Skip)
    # first coldstartup not counted
    model.statesExclusivity_3 = pyomo.Constraint(model.i, rule=lambda model, i:
                                            model.isColdStarted[0] == 0 ) 
    
    #transition from an off-state to a standby-state is not allowed    
    model.statesExclusivity_4 = pyomo.Constraint(model.i, rule=lambda model, i:
                                            model.isIdle[i-1] + model.isStandBy[i] <= 1 if i > 0 else pyomo.Constraint.Skip)     
    #sepcify hot startup timestep
    model.statesExclusivity_5 = pyomo.Constraint(model.i, rule=lambda model, i:
                                            model.isStandBy[i-1] <= model.isStandBy[i] + model.isHotStarted[i] if i > 0 else pyomo.Constraint.Skip)    
    
    #minimum runtime constraint
    def minRuntime_rule(model, i):
        #force the minimum runtime after a start event
        next_time_periods = {i + offset for offset in range(minRuntime) if i + offset < time_periods}
        return sum(model.isRunning[tt] + model.isStandBy[tt] for tt in next_time_periods) >= len(next_time_periods) * model.isColdStarted[i]
    model.minRuntime_rule = pyomo.Constraint(model.i, rule=minRuntime_rule)       

    #minimum downtime constraint
    def minDownTime_rule(model, i):
        if i == 0:
            return pyomo.Constraint.Skip
        previous_time_periods = {i - offset for offset in range(1, minDowntime + 1) if i - offset >=0}
        return len(previous_time_periods) * model.isColdStarted[i] <= sum(model.isIdle[tt] for tt in previous_time_periods)
    model.minDownTime_rule = pyomo.Constraint(model.i, rule=minDownTime_rule)     
    
    #maximum allowed cold startups within defined time period    
    model.maxColdStartup_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                        sum(model.isColdStarted[i] for i in range(0, time_periods)) <= maxAllowedColdStartups) 

    model.electrolyzerConsumption_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                        model.prodH2_kg[i] == model.elecCons_MW[i]*0.25*effElec/energyContentH2_LHV*(1-model.isStandBy[i]) ) 
        
    model.hydrogenBalance_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                            model.prodH2_kg[i] == model.elecToPlantUse_kg[i] + model.elecToStorage_kg[i]) 

    model.demandBalance_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                            industry_demand[i] == model.elecToPlantUse_kg[i] + model.storageToPlantUse_kg[i])   
    
    model.elecColdStartUpCost_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                model.elecColdStartUpCons_MW[i] == 0.05*0.25*model.elecCapacity * model.isColdStarted[i])
    
    model.elecHotStartUpCost_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                model.elecHotStartUpCons_MW[i] == 0.005*0.25*model.elecCapacity * model.isHotStarted[i])
            
    model.compressorCons_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                model.comprCons_MW[i] == model.elecToStorage_kg[i] * compCons)
    
    model.standByConsumption_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                model.elecStandByCons_MW[i] == 0.01*0.25*model.elecCapacity*model.isStandBy[i])

    
    model.totalConsumption_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                            model.bidQuantity_MW[i] == model.elecCons_MW[i] +  model.comprCons_MW[i]+ model.elecHotStartUpCons_MW[i]+ model.elecColdStartUpCons_MW[i])
    
    # Define Storage constraint
    model.currentSOC_rule = pyomo.Constraint(model.i, rule=lambda model, i:
                                        model.currentSOC_kg[i] == model.currentSOC_kg[i - 1] + model.elecToStorage_kg[i] - model.storageToPlantUse_kg[i]
                                        if i > 0 else model.currentSOC_kg[i] == model.elecToStorage_kg[i]  - model.storageToPlantUse_kg[i])  
    
    model.maxSOC_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                        model.currentSOC_kg[i] <= model.storageCapacity)
    
    model.storageFlowRate_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                            model.storageToPlantUse_kg[i] <= 0.05*model.storageCapacity) 

#%%    # Solve the optimization problem
    opt = SolverFactory("gurobi")  # You can replace this with your preferred solver
    result = opt.solve(model, tee=True)
    print('Solver status:', result.solver.status)
    print('Termination condition: ', result.solver.termination_condition)

    # Retrieve the optimal values
    elecCapacity = model.elecCapacity.value
    storageCapacity = model.storageCapacity.value
    optimalBidamount = [model.bidQuantity_MW[i].value for i in model.i]
    elecCons = [model.elecCons_MW[i].value for i in model.i]            
    elecStandByCons = [model.elecStandByCons_MW[i].value for i in model.i]           
    comprCons = [model.comprCons_MW[i].value for i in model.i]
    prodH2 = [ model.prodH2_kg[i].value for i in model.i]           
    elecToPlantUse_kg = [ model.elecToPlantUse_kg[i].value for i in model.i]            
    elecToStorage_kg = [ model.elecToStorage_kg[i].value for i in model.i]            
    storageToPlantUse_kg = [ model.storageToPlantUse_kg[i].value for i in model.i]            
    currentSOC = [model.currentSOC_kg[i].value for i in model.i]                
    isRunning =   [model.isRunning[i].value for i in model.i]
    isIdle = [model.isIdle[i].value for i in model.i]
    isStandBy = [model.isStandBy[i].value for i in model.i]
    isColdStarted = [model.isColdStarted[i].value for i in model.i]
    isHotStarted = [model.isHotStarted[i].value for i in model.i]
    return elecCapacity, storageCapacity, optimalBidamount,elecCons, elecStandByCons, comprCons,  prodH2, elecToPlantUse_kg, elecToStorage_kg, storageToPlantUse_kg, currentSOC, isRunning, isIdle, isStandBy, isColdStarted, isHotStarted

#set up user input variables
optTimeframe = 'year' #input("Choose optimization timefrme, day or week : ")

opt_elecCapacity = []
opt_storageCapacity = []
allBidQuantity = []
allelecCons = []
all_elecStandByCons = []
allcomprCons = []
allprodH2 = []
allelecToPlantUse_kg = []
allelecToStorage_kg = []
allstorageToPlantUse_kg = []
allCurrentSOC = []
all_isRunning = []
all_isIdle = []
all_isStandBy = []
all_isColdStarted = []
all_isHotStarted = []

if optTimeframe == "year":
    time_periods = len(price)  
    elecCapacity, storageCapacity, optimalBidamount,elecCons,elecStandByCons, comprCons, prodH2, elecToPlantUse_kg, elecToStorage_kg, storageToPlantUse_kg, currentSOC, isRunning, isIdle, isStandBy, isColdStarted, isHotStarted = optimizeH2Prod(price=price, industry_demand=industry_demand, time_periods=time_periods)   
    opt_elecCapacity.append(elecCapacity)
    opt_storageCapacity.append(storageCapacity)
    allBidQuantity.extend([round(item, 3) for item in optimalBidamount])
    allelecCons.extend([round(item, 3) for item in elecCons])
    all_elecStandByCons.extend(elecStandByCons)        
    allcomprCons.extend([round(item, 3) for item in comprCons])
    allprodH2.extend([round(item, 3) for item in prodH2])
    allelecToPlantUse_kg.extend([round(item, 3) for item in elecToPlantUse_kg])
    allelecToStorage_kg.extend([round(item, 3) for item in elecToStorage_kg])
    allstorageToPlantUse_kg.extend([round(item, 3) for item in storageToPlantUse_kg])
    allCurrentSOC.extend([round(item, 3) for item in currentSOC])
    all_isRunning.extend(isRunning)
    all_isIdle.extend(isIdle), 
    all_isStandBy.extend(isStandBy),        
    all_isColdStarted.extend(isColdStarted) 
    all_isHotStarted.extend(isHotStarted)    

print(opt_elecCapacity, 'opt_elecCapacity')
print(opt_storageCapacity, 'opt_storageCapacity')

# Export variables to CSV file
data = {'industry_demand': industry_demand,
        'optimalBidamount': allBidQuantity,
        'elecStandByCons': all_elecStandByCons,
        'elecCons': allelecCons,
        'comprCons': allcomprCons, 
        'prodH2': allprodH2,
        'elecToPlantUse_kg':allelecToPlantUse_kg,
        'elecToStorage_kg':allelecToStorage_kg,
        'storageToPlantUse_kg':allstorageToPlantUse_kg, 
        'currentSOC': allCurrentSOC, 
        'price': price, 
        'all_isRunning':all_isRunning,
        'isIdle': all_isIdle,
        'isStandBy':all_isStandBy,
        'isColdStarted': all_isColdStarted,
        'isHotStarted': all_isHotStarted,
        }
for key, value in data.items():
    print(f'Length of data in "{key}" is {len(value)}')
df = pd.DataFrame(data)
df.to_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/flexABLE_w_electrolyzer/Data_processing/optimizedBidAmount_3states_w_capacity.csv', index=True)



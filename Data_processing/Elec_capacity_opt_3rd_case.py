
import pandas as pd 
import pyomo.environ as pyomo
from pyomo.opt import SolverFactory 

# electrolyzers = pd.read_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/flexABLE_w_electrolyzer/input/2016/electrolyzers.csv')
energyContentH2_LHV = 0.03333 #MWh/kg or lower heating value

#Electrolyzer Parameters PEM
minLoad_PEM = 0.05 #[%]
maxLoad_PEM = 1.2 #[%]
minDowntime_PEM = 2 #hours 0.5/0.25
effElec_PEM = 0.63 #average electrolyzer efficiency[%]
investmentCost_PEM = 1078000/20 #Euro/MW

#Electrolyzer Parameters PEM
minLoad_AEL= 0.15 #[%]
maxLoad_AEL = 1 #[%]
minDowntime_AEL = 4 #hours 1/0.25
effElec_AEL = 0.65 
investmentCost_AEL = 902000/20 #Euro/MW

# energyContentH2_HHV = 0.03939 #MWh/kg or higher heating value

#common  parameters
standbyCons = 0.05 #5% of capacity[MW]
maxAllowedColdStartups = 5000/20
coldStartUpCost = 50 #Euro/MW capacity

#system parameters
maxSOC = 2763950 #1381975 #kg
compCons = 0.0012 #specific compressor consumption [MWh/kg]
investmentCost_storage = 530/30 #Euro/kg
investmentCost_compress = 2500 #Euro/kg/hr converted to 15 min value

industrialDemandH2 = pd.read_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/flexABLE_w_electrolyzer/input/2019/industrial_demand.csv')  #should be in kilos 
price_signal = pd.read_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/flexABLE_w_electrolyzer/output/2019/EOM_Prices.csv')

#Specify which industry to analyze here
industrialDemandH2 = industrialDemandH2['Iron_steel'][0:960]
price_signal = price_signal['Price'][0:960]

# Convert DataFrame columns to lists 
price = price_signal.tolist()
industry_demand = industrialDemandH2.tolist()


#specify optimization function
def optimizeH2Prod(investmentCost_elec, effElec, maxLoad, minLoad, minDowntime, price, industry_demand, time_periods):
    model = pyomo.ConcreteModel('Optimized Electroluzer Bidding')
    model.i = pyomo.RangeSet(0, len(price) - 1)
    
    # Define the decision variables
    #optimized capacities
    model.elecCapacity = pyomo.Var(domain=pyomo.NonNegativeReals) #MW of installed capacity    
    model.bidQuantity_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals)
    model.prodH2_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #produced H2
    model.elecCons_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #electrolyzer consumption per kg
    model.elecStandByCons_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #electrolyzer consumption per kg
    model.elecColdStartUpCost_EUR = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #electrolyzer consumption per kg
    model.comprCons_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #compressor consumption per kg
    model.elecToStorage_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #H2 from electrolyzer to storage
    model.elecToPlantUse_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #H2 from electrolyzer to process
    model.storageToPlantUse_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #H2 from storage to process
    model.currentSOC_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #Status of Storage

    # Binary variable to represent the status of the electrolyzer (on/off)
    model.isRunning = pyomo.Var(model.i, domain=pyomo.Binary, doc='Electrolyzer running')
    model.isColdStarted = pyomo.Var(model.i, domain=pyomo.Binary, doc='Electrolyzer  start from idle')
    model.isIdle = pyomo.Var(model.i, domain=pyomo.Binary, doc='Electrolyzer is idle')
    model.isStandBy = pyomo.Var(model.i, domain=pyomo.Binary, doc='Electrolyzer isStandBy')

    # Define the objective function
    model.obj = pyomo.Objective(expr=investmentCost_elec * model.elecCapacity + sum(price[i] * model.bidQuantity_MW[i] * 0.25 + model.elecColdStartUpCost_EUR[i] for i in model.i), sense=pyomo.minimize)
    # sum(price[i] * model.bidQuantity_MW[i] * 0.25 + model.elecColdStartUpCost_EUR[i] for i in model.i) investmentCost_storage * model.storageCapacity + \
    #Max power boundary
    model.maxPower_rule = pyomo.Constraint(model.i, rule=lambda model, i:
                                            model.elecCons_MW[i] <= model.elecCapacity * maxLoad * model.isRunning[i] + standbyCons * model.elecCapacity * model.isStandBy[i] )
    #min power boundary
    model.minPower_rule = pyomo.Constraint(model.i, rule=lambda model, i: #minimum power is 10% of installed capacity
                                            model.elecCons_MW[i] >= minLoad * model.elecCapacity * model.isRunning[i] + standbyCons*model.elecCapacity*model.isStandBy[i])
    #only one operational mode
    model.statesExclusivity = pyomo.Constraint(model.i, rule=lambda model, i:
                                            model.isRunning[i] + model.isIdle[i] + model.isStandBy[i] == 1)
    #transition from off to on state
    model.statesExclusivity_2 = pyomo.Constraint(model.i, rule=lambda model, i:
                                            model.isColdStarted[i] >= model.isRunning[i] - model.isRunning[i-1]- model.isStandBy[i-1] if i > 0 else pyomo.Constraint.Skip)
    # # first timestep is counted as coldstartup
    model.statesExclusivity_3 = pyomo.Constraint(model.i, rule=lambda model, i:
                                            model.isColdStarted[0] == 0 ) 
    
    #transition from an off-state to a standby-state is not allowed    
    model.statesExclusivity_4 = pyomo.Constraint(model.i, rule=lambda model, i:
                                            model.isIdle[i-1] + model.isStandBy[i] <= 1 if i > 0 else pyomo.Constraint.Skip)     
    
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
                                        model.prodH2_kg[i] == model.elecCons_MW[i] * 0.25 * effElec/energyContentH2_LHV*(1-model.isStandBy[i]) ) 
        
    model.hydrogenBalance_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                            model.prodH2_kg[i] == model.elecToPlantUse_kg[i] + model.elecToStorage_kg[i]) 

    model.demandBalance_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                            industry_demand[i] == model.elecToPlantUse_kg[i] + model.storageToPlantUse_kg[i])   
    
    model.elecColdStartUpCost_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                model.elecColdStartUpCost_EUR[i] == model.elecCapacity * coldStartUpCost * model.isColdStarted[i])

    model.standByConsumption_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                model.elecStandByCons_MW[i] == standbyCons * model.elecCapacity * model.isStandBy[i])
                    
    model.compressorCons_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                model.comprCons_MW[i] == model.elecToStorage_kg[i] * compCons/0.25) #15min power value
    
    model.totalConsumption_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
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
    elecCapacity = model.elecCapacity.value
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
    return elecCapacity, optimalBidamount,elecCons, elecStandByCons, comprCons,  prodH2, elecToPlantUse_kg, elecToStorage_kg, storageToPlantUse_kg, currentSOC, isRunning, isIdle, isStandBy, isColdStarted

#set up user input variables
optTimeframe = 'year'
elec_type = 'PEM'

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


if optTimeframe == "year":
    time_periods = len(price)  
    if elec_type == 'PEM':  
        elecCapacity, optimalBidamount, \
            elecCons,elecStandByCons, comprCons, prodH2, elecToPlantUse_kg, elecToStorage_kg, storageToPlantUse_kg, currentSOC, \
                isRunning, isIdle, isStandBy, isColdStarted = optimizeH2Prod(investmentCost_elec = investmentCost_PEM, effElec = effElec_PEM, \
                                                                            maxLoad = maxLoad_PEM, minLoad = minLoad_PEM, minDowntime = minDowntime_PEM, \
                                                                            price=price, industry_demand=industry_demand, time_periods=time_periods)   
    elif elec_type == 'AEL': 
        elecCapacity, optimalBidamount, \
        elecCons,elecStandByCons, comprCons, prodH2, elecToPlantUse_kg, elecToStorage_kg, storageToPlantUse_kg, currentSOC, \
            isRunning, isIdle, isStandBy, isColdStarted = optimizeH2Prod(investmentCost_elec = investmentCost_PEM, effElec = effElec_PEM, \
                                                                        maxLoad = maxLoad_PEM, minLoad = minLoad_PEM, minDowntime = minDowntime_PEM, \
                                                                            price=price, industry_demand=industry_demand, time_periods=time_periods)   

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

compressorCapacity = max(allelecToStorage_kg)*4
print(elecCapacity, 'elecCapacity')
print(compressorCapacity, 'compressorCapacity')


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
        'isRunning':all_isRunning,
        'isIdle': all_isIdle,
        'isStandBy':all_isStandBy,
        'isColdStarted': all_isColdStarted,
        }

# df = pd.DataFrame(data)
# df.to_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/flexABLE_w_electrolyzer/Data_processing/optimizedBidAmount_w_opt_capacity.csv', index=True)



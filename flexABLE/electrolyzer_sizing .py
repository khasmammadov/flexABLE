import pandas as pd 
import pyomo.environ as pyomo
from pyomo.opt import SolverFactory 
import pandas as pd

investmentCost_storage = 1000  #Euro per kilo of storage
energyContentH2_LHV = 0.03333 #MWh/kg or lower heating value of H2
effElec_PEM = 0.7
effElec_AEL = 0.6
investmentCost_elec_PEM = 1078000 #Euro/MW
investmentCost_elec_AEL = 902000 #Euro/MW
# Read the electrolyzers.csv file
electrolyzers_df = pd.read_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/flexABLE_w_electrolyzer/input/2016/electrolyzers.csv')
demand_df = pd.read_csv('/Users/kanankhasmammadov/Desktop/Thesis - Electrolyzer market participation/flexABLE_w_electrolyzer/input/2016/industrial_demand.csv')

#Specify industrial demands
demand_elec_x = demand_df['Elec_x']

def capacity_optimization(investmentCost_elec, effElec, industry_demand):
    model = pyomo.ConcreteModel()
    model.i = pyomo.RangeSet(0, len(industry_demand) - 1)

    # Define the decision variables
    model.totalInvestment = pyomo.Var(domain=pyomo.NonNegativeReals)
    model.elecCapacity = pyomo.Var(domain=pyomo.NonNegativeReals)
    model.storageCapacity = pyomo.Var(domain=pyomo.NonNegativeReals)
    model.elecToPlantUse_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals)
    model.elecToStorage_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals)
    model.storageToPlantUse_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals)
    model.prodH2_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals)
    model.elecCons_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals)
    model.currentSOC_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals)
    
    model.maxPower_rule = pyomo.Constraint(model.i, rule=lambda model, i:
                                            model.elecCons_MW[i] <= model.elecCapacity)

    model.minPower_rule1 = pyomo.Constraint(model.i, rule=lambda model, i:
                                            model.elecCons_MW[i] >= 0.1 * model.elecCapacity)

    model.electrolyzerConsumption_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                        model.prodH2_kg[i] == model.elecCons_MW[i]*0.25*effElec/energyContentH2_LHV )

    model.hydrogenBalance_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                            model.prodH2_kg[i] == model.elecToPlantUse_kg[i] + model.elecToStorage_kg[i])

    model.demandBalance_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                            industry_demand[i] == model.elecToPlantUse_kg[i] + model.storageToPlantUse_kg[i])   
    # Define Storage constraint
    model.currentSOC_rule = pyomo.Constraint(model.i, rule=lambda model, i:
                                        model.currentSOC_kg[i] == model.currentSOC_kg[i - 1] + model.elecToStorage_kg[i] - model.storageToPlantUse_kg[i]
                                        if i > 0 else model.currentSOC_kg[i] == model.elecToStorage_kg[i]  - model.storageToPlantUse_kg[i])  
    
    model.maxSOC_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                        model.currentSOC_kg[i] <= model.storageCapacity)
    
    def investmentCost_rule(model): #objective function for cost minimization, conventional energy sources are prioritized by their CO2 output in ascending order
            return model.totalInvestment ==  investmentCost_elec * model.elecCapacity + investmentCost_storage*model.storageCapacity
    model.investmentCost_rule = pyomo.Constraint(rule=investmentCost_rule)
    
    def ObjRule(model):
        return model.totalInvestment
    
    model.obj1 = pyomo.Objective(rule = ObjRule, sense = pyomo.minimize) #minimizing investment cost 
    opt = SolverFactory("gurobi_direct") 
    opt.solve(model) 
        
    elecCapacity = [model.elecCapacity.value]
    storageCapacity = [model.storageCapacity.value]
    elecToPlantUse_kg = [model.elecToPlantUse_kg[i].value for i in model.i]
    storageToPlantUse_kg = [model.storageToPlantUse_kg[i].value for i in model.i]
    prodH2_kg = [model.prodH2_kg[i].value for i in model.i]
    elecCons_MW = [model.elecCons_MW[i].value for i in model.i]
    currentSOC_kg = [model.currentSOC_kg[i].value for i in model.i]    
    return elecCapacity, storageCapacity, elecToPlantUse_kg, storageToPlantUse_kg, prodH2_kg, elecCons_MW, currentSOC_kg


elecCapacity_x = []
storageCapacity_x = []
elecToPlantUse_kg_x = []
storageToPlantUse_kg_x = []
prodH2_kg_x = []
elecCons_MW_x = []
currentSOC_kg_x  = []

elecCapacity, storageCapacity, elecToPlantUse_kg, storageToPlantUse_kg, prodH2_kg, elecCons_MW, currentSOC_kg = capacity_optimization(investmentCost_elec = investmentCost_elec_PEM, effElec = effElec_PEM, industry_demand = demand_elec_x)
elecCapacity_x.append(elecCapacity)                    
storageCapacity_x.append(storageCapacity) 
elecToPlantUse_kg_x.append(elecToPlantUse_kg) 
storageToPlantUse_kg_x.append(storageToPlantUse_kg) 
prodH2_kg_x.append(prodH2_kg) 
elecCons_MW_x.append(elecCons_MW) 
currentSOC_kg_x.append(currentSOC_kg) 

output_elec_x = {
            'elecCapacity': elecCapacity_x,
            'storageCapacity': storageCapacity_x,
            'elecToPlantUse_kg': elecToPlantUse_kg_x,
            'storageToPlantUse_kg': storageToPlantUse_kg_x,
            'prodH2_kg': prodH2_kg_x,
            'elecCons_MW': elecCons_MW_x,
            'currentSOC_kg': currentSOC_kg_x}

df = pd.DataFrame(output_elec_x)
df.to_csv('capacity_optimization.csv', index=True)
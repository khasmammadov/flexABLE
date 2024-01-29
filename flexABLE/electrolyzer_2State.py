from .auxFunc import initializer
from .bid import Bid
import numpy as np
import pandas as pd 
import pyomo.environ as pyomo
from pyomo.opt import SolverFactory 
import os
import pandas as pd
import datetime

class Electrolyzer():
    @initializer
    def __init__(self,
                 agent=None,
                 name = 'Elec_x',
                 technology = 'PEM',
                 minPower = 10, #[MW]
                 installedCapacity = 100, #[MW] max power 
                 effElec = 0.7, #electrolyzer efficiency[%]
                 minDowntime = 0.5, #minimum standby time hours
                 minRuntime = 2, #hours
                 startUpCost = 5000, # Euro per MW installed capacity
                 maxAllowedColdStartups = 3000, #yearly allowed max cold startups
                 standbyCons = 1, #[MW] Stanby consumption of electrolyzer 1% per installed capacity
                 compEff = 0.75, # mechanical efficiency in %
                 compPressIn = 30, # inlet pressure in bar
                 compPressOut = 300, # outlet pressure in bar
                 compTempIn = 40, # inlet temperature in C
                 maxSOC = 2000, #Kg
                 maxStorageOutput = 800, #[kg/hr] max flow output of hydrogen storage 
                 industry = 'Refining', 
                 world = None,
                 node = None,
                 **kwargs):
        
        
        self.energyContentH2_LHV = 0.03333 #MWh/kg or lower heating value of H2
        self.startUpCost *= self.installedCapacity
        #adjusting hourly values for 15 min simulation interval
        self.minRuntime /= self.world.dt
        self.minDowntime /= self.world.dt
        self.standbyCons *= self.world.dt 
        self.maxStorageOutput *= self.world.dt 
        
        # bids status parameters
        self.dictCapacity = {n:0 for n in self.world.snapshots}
        self.sentBids = []

        self.dictCapacity[-1] = 0 #used to avoid key value in minimum downtime condition
        
        
    #For the production of 1kg of hydrogen, about 9 kg of water and 60kWh of electricity are consumed(Rievaj, V., Gaňa, J., & Synák, F. (2019). Is hydrogen the fuel of the future?)
    def step(self): 
        self.dictCapacity[self.world.currstep] = 0 #It initializes the available capacity at the current time step to zero.
        for bid in self.sentBids: 
            if 'demandEOM' in bid.ID: #If the bid's ID contains the substring 'demandEOM', it increases the available capacity at the current time step
                self.dictCapacity[self.world.currstep] = bid.confirmedAmount

    #clarify
    def feedback(self, bid):
        self.sentBids.append(bid)
        
    # generate and return a list of bids 
    def requestBid(self, t, market="EOM"):
        bids = []
        if market == "EOM":
            bids.extend(self.calculateBidEOM(t))
        return bids

    #this function is for collecting optimized bid amounts for EOM market
    def collectBidsEOM(self, t, bidsEOM, bidQuantity_demand):
            bidsEOM.append(Bid(issuer = self,
                                ID = "{}_demandEOM".format(self.name),
                                price = 300, #to make sure all bids gets confirmation
                                amount = bidQuantity_demand,
                                status = "Sent",
                                bidType = "Demand",
                                node = self.node))
            return bidsEOM

    # calculation EOM bid
    def calculateBidEOM(self, t):
        bidsEOM = []
        if os.path.exists('output/{}/Elec_capacities/{}_optimizedBidAmount.csv'.format(self.world.scenario, self.name)):
            optimization_results = pd.read_csv('output/{}/Elec_capacities/{}_optimizedBidAmount.csv'.format(self.world.scenario, self.name))
            bidQuantity_demand = optimization_results["bidQuantity"][t]             
            bidsEOM = self.collectBidsEOM(t, bidsEOM, bidQuantity_demand) 
        else:             
            #calculate compressor consumption based on input values          
            def compressorConsumtion(compEff, compPressIn, compPressOut, compTempIn):
                gamma = 1.4 # adiabatic exponent
                inlet_temperature = compTempIn + 273.15 # inlet temperature in K
                R = 8.314 # universal gas constant in J/mol*K
                M_H2_kg = 2.0159E-03 # molar mass of H2 in kg/mol
                compCons = R * inlet_temperature / M_H2_kg * gamma / (gamma-1) * 1 / compEff * ((compPressOut/compPressIn)**((gamma-1)/gamma)-1) * 1E-06 / 3600 # compressor consumption in MWh/kg H2
                return compCons
            compCons = compressorConsumtion(compEff=self.compEff, compPressIn=self.compPressIn, compPressOut=self.compPressOut, compTempIn=self.compTempIn)*self.world.dt 

            # Defining optimization function       
            def  optimizeH2Prod(price, industry_demand, time_periods, maxAllowedColdStartups):
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
                
                # Define the objective function - minimize cost sum within selected timeframe
                model.obj = pyomo.Objective(expr=sum(price[i] * model.bidQuantity_MW[i] + model.elecstartUpCost_EUR[i] for i in model.i), sense=pyomo.minimize)

                #electrolyzer can only be running if it was running in the prior period or started in this one
                def electrolyzerStarted(model, i): 
                    if i == 0:
                        return pyomo.Constraint.Skip
                    else:
                        return model.isRunning[i]<= model.isRunning[i-1] + model.isStarted[i]
                model.electrolyzerStarted = pyomo.Constraint(model.i, rule=electrolyzerStarted)    
                
                #minimum run time constraint
                def minRuntime_rule(model, i):
                    next_time_periods = {i + offset for offset in range(int(self.minRuntime)) if i + offset < time_periods}
                    return sum(model.isRunning[tt] for tt in next_time_periods) >= len(next_time_periods) * model.isStarted[i]
                model.minRuntime_rule = pyomo.Constraint(model.i, rule=minRuntime_rule)       
                
                #minimum StandbyTime time constraint
                def minDownTime_rule(model, i):
                    if i == 0:
                        return pyomo.Constraint.Skip
                    previous_time_periods = {i - offset for offset in range(1, int(self.minDowntime) + 1) if i - offset >=0}
                    return len(previous_time_periods) * model.isStarted[i] <= sum(1-model.isRunning[tt] for tt in previous_time_periods)
                model.minDownTime_rule = pyomo.Constraint(model.i, rule=minDownTime_rule)     

                model.maxColdStartup_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                    sum(model.isStarted[i] for i in range(0, time_periods)) <= maxAllowedColdStartups)     
                
                # Maximum power constraint of electrolyzer
                model.installedCapacity_rule = pyomo.Constraint(model.i, rule=lambda model, i:
                                                        model.elecCons_MW[i] <= self.installedCapacity * model.isRunning[i])
                # Minimum power constraint of electrolyzer
                model.minPower_rule = pyomo.Constraint(model.i, rule=lambda model, i:
                                                        model.elecCons_MW[i] >= self.minPower * model.isRunning[i])                

                model.totalProducedH2 = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                    model.elecCons_MW[i] ==  model.prodH2_kg[i] / 0.25 / self.effElec * self.energyContentH2_LHV)
                
                model.hydrogenBalance_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                        model.prodH2_kg[i] == model.elecToPlantUse_kg[i] + model.elecToStorage_kg[i]) 

                model.demandBalance_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                        industry_demand[i] == model.elecToPlantUse_kg[i] + model.storageToPlantUse_kg[i])                     
                
                model.elecstartUpCost_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                            model.elecstartUpCost_EUR[i] == self.startUpCost * model.isStarted[i])                    
                
                model.comprConsumption_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                            model.comprCons_MW[i] == model.elecToStorage_kg[i] * comprCons)
            
                model.electricalBalance_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                        model.bidQuantity_MW[i] == model.elecCons_MW[i] +  model.comprCons_MW[i]) 
                # Define Storage constraint
                model.currentSOC_rule = pyomo.Constraint(model.i, rule=lambda model, i:
                                                    model.currentSOC_kg[i] == model.currentSOC_kg[i - 1] + model.elecToStorage_kg[i] - model.storageToPlantUse_kg[i]
                                                    if i > 0 else model.currentSOC_kg[i] == model.elecToStorage_kg[i]  - model.storageToPlantUse_kg[i])  
                
                model.maxSOC_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                    model.currentSOC_kg[i] <= self.maxSOC)
                
                model.storageFlowRate_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                        model.storageToPlantUse_kg[i] <= self.maxStorageOutput)  
                # Solve the optimization problem
                opt = SolverFactory("gurobi")  # You can replace this with your preferred solver
                result = opt.solve(model ) #tee=Trues
                print('INFO: Solver status:', result.solver.status)
                print('INFO: Results: ', result.solver.termination_condition)

                # Retrieve the optimal values
                optimalBidAmount = [model.bidQuantity_MW[i].value for i in model.i]
                elecCons = [model.elecCons_MW[i].value for i in model.i]            
                comprCons = [model.comprCons_MW[i].value for i in model.i]
                prodH2 = [ model.prodH2_kg[i].value for i in model.i]           
                elecToPlantUse_kg = [ model.elecToPlantUse_kg[i].value for i in model.i]            
                elecToStorage_kg = [ model.elecToStorage_kg[i].value for i in model.i]            
                storageToPlantUse_kg = [ model.storageToPlantUse_kg[i].value for i in model.i]            
                currentSOC = [model.currentSOC_kg[i].value for i in model.i]                
                isRunning =   [model.isRunning[i].value for i in model.i]
                isStarted = [model.isStarted[i].value for i in model.i]
                return optimalBidAmount,elecCons, comprCons,  prodH2, elecToPlantUse_kg, elecToStorage_kg, storageToPlantUse_kg, currentSOC, isRunning, isStarted

            #setup optimization input data from flexable
            industrialDemandH2 = self.world.industrial_demand[self.name]
            industrialDemandH2 = pd.DataFrame(industrialDemandH2, columns=[self.name])            
            PFC = [round(p, 2) for p in self.world.PFC]
            PFC = pd.DataFrame(PFC, columns=['PFC'])

            #set up timeframe for optimization
            optTimeframe = 'year' #input("Choose optimization timefrme, day or week : ")
            simulationYear = 2016 #please specify year
            lastDay = 15 #please specify day

            start_of_year = datetime.datetime(year=simulationYear, month=1, day=1)
            date = start_of_year + datetime.timedelta(days=lastDay - 1)
            lastMonth = date.month
            industrialDemandH2['Timestamp'] = pd.date_range(start=f'1/1/{simulationYear}', end=f'{lastMonth}/{lastDay}/{simulationYear} 23:45', freq='15T')            
            PFC['Timestamp'] = pd.date_range(start=f'1/1/{simulationYear}', end=f'{lastMonth}/{lastDay}/{simulationYear} 23:45', freq='15T')

            #optimization reults for all optimized days
            optimalBidAmount_all = [] 
            elecCons_all = []
            comprCons_all = []
            prodH2_all = []
            elecToPlantUse_kg_all = []
            elecToStorage_kg_all = []
            storageToPlantUse_kg_all = []
            currentSOC_all = []
            isRunning_all = []
            isStarted_all = []

            #setting optimization timeframe and calling optimization function
            if optTimeframe == "year":
                print('INFO: Optimization is being performed for entire time period')
                time_periods = len(PFC) 
                maxAllowedColdStartups = self.maxAllowedColdStartups/365*lastDay
                demand = list(industrialDemandH2[self.name])
                price = list(PFC['PFC'])
                #Perform optimization for entire time period
                optimalBidAmount,elecCons, comprCons, prodH2, elecToPlantUse_kg, elecToStorage_kg, storageToPlantUse_kg, currentSOC, isRunning, isStarted = optimizeH2Prod(price=price, industry_demand=demand, time_periods = time_periods, maxAllowedColdStartups=maxAllowedColdStartups)
                #output results
                optimalBidAmount_all.extend(optimalBidAmount)                    
                elecCons_all.extend(elecCons)
                comprCons_all.extend(comprCons)
                prodH2_all.extend(prodH2)
                elecToPlantUse_kg_all.extend(elecToPlantUse_kg)
                elecToStorage_kg_all.extend(elecToStorage_kg)
                storageToPlantUse_kg_all.extend(storageToPlantUse_kg)
                currentSOC_all.extend(currentSOC)
                isRunning_all.extend(isRunning)
                isStarted_all.extend(isStarted)            

            if optTimeframe == "month":
                print('INFO: Monthly optimization is being performed')
                # find weeks from timestamp
                industrialDemandH2['Month'] = industrialDemandH2['Timestamp'].dt.month
                PFC['Month'] = PFC['Timestamp'].dt.month
                unique_month = industrialDemandH2['Month'].unique()
                for month in unique_month:
                    # Extract weekly data for the current month
                    monthlyIntervalDemand = industrialDemandH2[industrialDemandH2['Month'] == month]
                    monthlyIntervalDemand = list(monthlyIntervalDemand[self.name])
                    monthlyIntervalPFC = PFC[PFC['Month'] == month]
                    monthlyIntervalPFC = list(monthlyIntervalPFC['PFC'])
                    time_periods = len(monthlyIntervalPFC) 
                    maxAllowedColdStartups = self.maxAllowedColdStartups/12
                    #Perform optimization for each week
                    optimalBidAmount,elecCons, comprCons, prodH2, elecToPlantUse_kg, elecToStorage_kg, storageToPlantUse_kg, currentSOC, isRunning, isStarted = optimizeH2Prod(price=monthlyIntervalPFC, industry_demand=monthlyIntervalDemand, time_periods = time_periods, maxAllowedColdStartups=maxAllowedColdStartups)                    
                    #output results
                    optimalBidAmount_all.extend(optimalBidAmount)                    
                    elecCons_all.extend(elecCons)
                    comprCons_all.extend(comprCons)
                    prodH2_all.extend(prodH2)
                    elecToPlantUse_kg_all.extend(elecToPlantUse_kg)
                    elecToStorage_kg_all.extend(elecToStorage_kg)
                    storageToPlantUse_kg_all.extend(storageToPlantUse_kg)
                    currentSOC_all.extend(currentSOC)
                    isRunning_all.extend(isRunning)
                    isStarted_all.extend(isStarted)

            if optTimeframe == "week":
                print('INFO: Weekly optimization is being performed')
                # find weeks from timestamp
                industrialDemandH2['Week'] = industrialDemandH2['Timestamp'].dt.isocalendar().week
                PFC['Week'] = PFC['Timestamp'].dt.isocalendar().week
                unique_weeks = industrialDemandH2['Week'].unique()
                for week in unique_weeks:
                    # Extract weekly data for the current week
                    weeklyIntervalDemand = industrialDemandH2[industrialDemandH2['Week'] == week]
                    weeklyIntervalDemand = list(weeklyIntervalDemand[self.name])
                    weeklyIntervalPFC = PFC[PFC['Week'] == week]
                    weeklyIntervalPFC = list(weeklyIntervalPFC['PFC'])
                    time_periods = len(weeklyIntervalPFC) 
                    maxAllowedColdStartups = self.maxAllowedColdStartups/52
                    #Perform optimization for each week
                    optimalBidAmount,elecCons, comprCons, prodH2, elecToPlantUse_kg, elecToStorage_kg, storageToPlantUse_kg, currentSOC, isRunning, isStarted = optimizeH2Prod(price=weeklyIntervalPFC, industry_demand=weeklyIntervalDemand, time_periods = time_periods, maxAllowedColdStartups=maxAllowedColdStartups)
                    #output results
                    optimalBidAmount_all.extend(optimalBidAmount)                    
                    elecCons_all.extend(elecCons)
                    comprCons_all.extend(comprCons)
                    prodH2_all.extend(prodH2)
                    elecToPlantUse_kg_all.extend(elecToPlantUse_kg)
                    elecToStorage_kg_all.extend(elecToStorage_kg)
                    storageToPlantUse_kg_all.extend(storageToPlantUse_kg)
                    currentSOC_all.extend(currentSOC)
                    isRunning_all.extend(isRunning)
                    isStarted_all.extend(isStarted)

            elif optTimeframe == "day":
                print('INFO: Daily optimization is being performed')
                # find days from timestamp
                industrialDemandH2['Date'] = industrialDemandH2['Timestamp'].dt.date
                PFC['Date'] = PFC['Timestamp'].dt.date
                unique_days = industrialDemandH2['Date'].unique()
                for day in unique_days:
                    # Extract data for the current day
                    dailyIntervalDemand = industrialDemandH2[industrialDemandH2['Date'] == day]
                    dailyIntervalDemand = list(dailyIntervalDemand[self.name])
                    dailyIntervalPFC = PFC[PFC['Date'] == day]
                    dailyIntervalPFC = list(dailyIntervalPFC['PFC'])
                    time_periods = len(dailyIntervalPFC)  
                    maxAllowedColdStartups = self.maxAllowedColdStartups/365
                    print(maxAllowedColdStartups, 'maxAllowedColdStartups')
                    #Perform optimization for each day
                    optimalBidAmount,elecCons, comprCons, prodH2, elecToPlantUse_kg, elecToStorage_kg,storageToPlantUse_kg, currentSOC, isRunning, isStarted = optimizeH2Prod(price=dailyIntervalPFC, industry_demand=dailyIntervalDemand, time_periods = time_periods, maxAllowedColdStartups=maxAllowedColdStartups)

                    #output results into CSV
                    optimalBidAmount_all.extend(optimalBidAmount)                    
                    elecCons_all.extend(elecCons)
                    comprCons_all.extend(comprCons)
                    prodH2_all.extend(prodH2)
                    elecToPlantUse_kg_all.extend(elecToPlantUse_kg)
                    elecToStorage_kg_all.extend(elecToStorage_kg)
                    storageToPlantUse_kg_all.extend(storageToPlantUse_kg)
                    currentSOC_all.extend(currentSOC)
                    isRunning_all.extend(isRunning)
                    isStarted_all.extend(isStarted)
            
            #exporting optimization results, happens one time then code uses exported csv file for the rest of the simulation
            directory = 'output/{}/Elec_capacities'.format(self.world.scenario)
            if not os.path.exists(directory):
                os.makedirs(directory)
            output = {'timestamp': industrialDemandH2['Timestamp'], 
                        'bidQuantity': optimalBidAmount_all,
                        'electrolyzer_consumption': elecCons_all,
                        'compressor_consumption': comprCons_all,
                        'produced_h2': prodH2_all,
                        'electrolyzer_to_plant_h2': elecToPlantUse_kg_all,
                        'electrolyzer_to_storage_h2': elecToStorage_kg_all,
                        'storage_to_plant_h2': storageToPlantUse_kg_all,
                        'SOC': currentSOC_all,
                        'isRunning': isRunning_all,
                        'inStarted': isStarted_all,
                        'PFC': PFC['PFC'],
                        'h2demand': industrialDemandH2[self.name]}
            df = pd.DataFrame(output)
            df.to_csv( directory + '/{}_optimizedBidAmount.csv'.format(self.name), index=True)
            #save results into bid request
            bidQuantity_demand = optimalBidAmount_all[t]
            bidsEOM = self.collectBidsEOM(t, bidsEOM, bidQuantity_demand)
        return bidsEOM

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
                 specEnerCons = 0.005, #System Specific energy consumption per m3 H2 [MWh/Nm3]                 
                 minDowntime = 0.5, #minimum standby time hours
                 minRuntime = 2, #hours
                 shutDownafterInactivity = 3, #[hr]after certain period of standby mode, Electrolyzer turns off 
                 startUpCost = 50, # Euro per MW installed capacity
                 standbyCons = 0.2, #[MW] Stanby consumption of electrolyzer 1% per installed capacity
                 maxAllowedColdStartups = 3000, #yearly allowed max cold startups
                 comprCons = 0.012,  #[MW]Compressor consumption 
                 maxSOC = 2000, #Kg 
                 industry = 'Refining', 
                 world = None,
                 node = None,
                 **kwargs):
        
        self.energyContentH2_LHV = 0.03333 #MWh/kg or lower heating value of H2
        self.minRuntime /= self.world.dt
        self.minDowntime /= self.world.dt          
        self.shutDownafterInactivity /= self.world.dt          
        
        self.storageFlowOutput = 200 #*self.world.dt
        # bids status parameters
        self.dictCapacity = {n:0 for n in self.world.snapshots}
        self.dictCapacity[-1] = 0 #used to avoid key value in minimum downtime condition
        
        # Unit status parameters
        self.sentBids = []
        
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
            
            # #startup consumption calculation
            # isRunning_np = np.array(optimization_results['isRunning'])
            # isRunning_diff = np.diff(isRunning_np)
            # isRunning_diff = np.append(isRunning_diff, 0)  # Add 0 at the end to match the length of isRunning
            # consecutive_zeros_start = list(np.where(isRunning_diff == -1)[0])
            # consecutive_zeros_end = list(np.where(isRunning_diff == 1)[0])
            
            # if len(consecutive_zeros_start) > len(consecutive_zeros_end):
            #     consecutive_zeros_start.pop(-1)
            # elif  len(consecutive_zeros_start) < len(consecutive_zeros_end):
            #     consecutive_zeros_end.pop(-1)
            
            # for i in range(len(consecutive_zeros_start)):
            #     if consecutive_zeros_end[i] - consecutive_zeros_start[i] >= self.shutDownafterInactivity:
            #         optimalBidAmount[consecutive_zeros_end[i]+1] += self.startUpCost
            
            bidQuantity_demand = optimization_results["bidQuantity"][t]             
            bidsEOM = self.collectBidsEOM(t, bidsEOM, bidQuantity_demand) 
        else:             
            # # Calculate the maxSOC - Max SOC represents calculated  cumulative max total weekly or daily demand
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

            # Defining optimization function       
            def  optimizeH2Prod(price, industry_demand, time_periods, maxAllowedColdStartups):
                model = pyomo.ConcreteModel('Optimized Electroluzer Bidding')
                model.i = pyomo.RangeSet(0, len(price) - 1)
                model.bidQuantity_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals)
                model.prodH2_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #produced H2
                model.elecCons_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #electrolyzer consumption per kg
                model.elecStandByCons_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #electrolyzer consumption per kg
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
                                                            model.comprCons_MW[i] == model.elecToStorage_kg[i] * self.comprCons)
            
                model.electricalBalance_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                        model.bidQuantity_MW[i] == model.elecCons_MW[i] +  model.comprCons_MW[i]) 
                # Define Storage constraint
                model.currentSOC_rule = pyomo.Constraint(model.i, rule=lambda model, i:
                                                    model.currentSOC_kg[i] == model.currentSOC_kg[i - 1] + model.elecToStorage_kg[i] - model.storageToPlantUse_kg[i]
                                                    if i > 0 else model.currentSOC_kg[i] == model.elecToStorage_kg[i]  - model.storageToPlantUse_kg[i])  
                
                model.maxSOC_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                    model.currentSOC_kg[i] <= self.maxSOC)
                
                model.storageFlowRate_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                        model.storageToPlantUse_kg[i] <= self.storageFlowOutput)  
                # Solve the optimization problem
                opt = SolverFactory("gurobi")  # You can replace this with your preferred solver
                result = opt.solve(model ) #tee=True
                
                print('INFO: Solver status:', result.solver.status)
                print('INFO: Results: ', result.solver.termination_condition)

                # Retrieve the optimal values
                optimalBidAmount = [model.bidQuantity_MW[i].value for i in model.i]
                elecCons = [model.elecCons_MW[i].value for i in model.i]            
                elecStandByCons = [model.elecStandByCons_MW[i].value for i in model.i]           
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
            optTimeframe = 'week' #input("Choose optimization timefrme, day or week : ")
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
                    
                    # #calculating stanby time, Standby consumption added to first timestep 
                    # standbyCount = isRunning.count(0)
                    # elecStandByCons = self.standbyCons * standbyCount
                    # cheapest_time = dailyIntervalPFC.index(min(weeklyIntervalPFC))
                    # optimalBidAmount[cheapest_time] += elecStandByCons 
                    
                    # #startup consumption calculation
                    # #add startup consumption to first active timestep
                    # first_active_timestep = isRunning.index(1)
                    # optimalBidAmount[int(first_active_timestep)] += self.startUpCost

                    # isRunning_np = np.array(isRunning)
                    # isRunning_diff = np.diff(isRunning_np)
                    # isRunning_diff = np.append(isRunning_diff, 0)  # Add 0 at the end to match the length of isRunning

                    # #adding startup consumption for consequetive inactivity time
                    # consecutive_zeros_start = list(np.where(isRunning_diff == -1)[0])
                    # consecutive_zeros_end = list(np.where(isRunning_diff == 1)[0])
                    # #adjust length of the lists
                    # if len(consecutive_zeros_start) > len(consecutive_zeros_end):
                    #     consecutive_zeros_start.pop(-1)
                    # elif  len(consecutive_zeros_start) < len(consecutive_zeros_end):
                    #     consecutive_zeros_end.pop(-1)
                    # #if inactivity is more than treshold, startUpCost added to next time when electrolyzer becomes online
                    # for i in range(len(consecutive_zeros_start)):
                    #     if consecutive_zeros_end[i] - consecutive_zeros_start[i] >= self.shutDownafterInactivity:
                    #         optimalBidAmount[consecutive_zeros_end[i]+1] += self.startUpCost
                    
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
                    
                    # #calculating stanby time, Standby consumption added to first timestep 
                    # standbyCount = isRunning.count(0)
                    # elecStandByCons = self.standbyCons * standbyCount
                    # cheapest_time = dailyIntervalPFC.index(min(dailyIntervalPFC))
                    # optimalBidAmount[cheapest_time] += elecStandByCons 
                    
                    # #startup consumption calculation
                    # #add startup consumption to first active timestep
                    # first_active_timestep = isRunning.index(1)
                    # optimalBidAmount[int(first_active_timestep)] += self.startUpCost

                    # isRunning_np = np.array(isRunning)
                    # isRunning_diff = np.diff(isRunning_np)
                    # isRunning_diff = np.append(isRunning_diff, 0)  # Add 0 at the end to match the length of isRunning

                    # #adding startup consumption for consequetive inactivity time
                    # consecutive_zeros_start = list(np.where(isRunning_diff == -1)[0])
                    # consecutive_zeros_end = list(np.where(isRunning_diff == 1)[0])
                    # #adjust length of the lists
                    # if len(consecutive_zeros_start) > len(consecutive_zeros_end):
                    #     consecutive_zeros_start.pop(-1)
                    # elif  len(consecutive_zeros_start) < len(consecutive_zeros_end):
                    #     consecutive_zeros_end.pop(-1)
                    # #if inactivity is more than treshold, startUpCostumption added to next time when electrolyzer becomes online
                    # for i in range(len(consecutive_zeros_start)):
                    #     if consecutive_zeros_end[i] - consecutive_zeros_start[i] >= self.shutDownafterInactivity:
                    #         optimalBidAmount[consecutive_zeros_end[i]+1] += self.startUpCost

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

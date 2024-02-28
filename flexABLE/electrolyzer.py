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
                minLoad = 0.1, #[%]
                maxLoad = 1.2, #%
                installedCapacity = 100, #[MW] installed capacity
                effElec = 0.7, #electrolyzer efficiency[%]
                minDowntime = 0.5, #minimum downtime
                minRuntime = 1, #hours
                coldStartUpCost = 50, # Euro per MW installed capacity
                maxAllowedColdStartups = 3000, #yearly allowed max cold startups
                standbyCons = 0.05, #% of installed capacity 
                comprCons = 0.0012, #MWh/kg  compressor specific consumptin
                maxSOC = 2000, #Kg
                industry = 'Refining', 
                world = None,
                node = None,
                 **kwargs):
        
        self.energyContentH2_LHV = 0.03333 #MWh/kg or lower heating value of H2
        #adjusting hourly values for 15 min simulation interval
        self.minRuntime /= self.world.dt
        self.minDowntime /= self.world.dt     
        self.coldStartUpCost *= self.installedCapacity
        self.minPower = self.installedCapacity * self.minLoad #[MW]
        self.maxPower = self.installedCapacity * self.maxLoad
        self.standbyCons *= self.installedCapacity
        # self.maxStorageOutput = self.maxSOC*0.1*self.world.dt #10% of storage capacity

        # bids status parameters
        self.dictCapacity = {n:0 for n in self.world.snapshots}
        self.sentBids = []
        self.dictCapacity[-1] = 0 

    #For the production of 1kg of hydrogen, about 9 kg of water and 60kWh of electricity are consumed(Rievaj, V., Gaňa, J., & Synák, F. (2019). Is hydrogen the fuel of the future?)
    def step(self): 
        # self.dictCapacity[self.world.currstep] = 0 #It initializes the available capacity at the current time step to zero.
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
            # # from Baumhof, M. T., Raheli, E., Johnsen, A. G., & Kazempour, J. (2023). Optimization of Hybrid Power Plants: When Is a Detailed Electrolyzer Model Necessary? https://doi.org/10.1109/PowerTech55446.2023.10202860        
            # def compressorConsumtion(compEff, compPressIn, compPressOut, compTempIn):
            #     gamma = 1.4 # adiabatic exponent
            #     inlet_temperature = compTempIn + 273.15 # inlet temperature in K
            #     R = 8.314 # universal gas constant in J/mol*K
            #     M_H2_kg = 2.0159E-03 # molar mass of H2 in kg/mol
            #     compCons = R * inlet_temperature / M_H2_kg * gamma / (gamma-1) * 1 / compEff * ((compPressOut/compPressIn)**((gamma-1)/gamma)-1) * 1E-06 / 3600 # compressor consumption in MWh/kg H2
            #     return compCons
            # compCons = compressorConsumtion(compEff=self.compEff, compPressIn=self.compPressIn, compPressOut=self.compPressOut, compTempIn=self.compTempIn) *self.world.dt 

            # Defining optimization function       
            def  optimizeH2Prod(price, industry_demand, time_periods, maxAllowedColdStartups):
                model = pyomo.ConcreteModel('Optimized Electroluzer Bidding')
                model.i = pyomo.RangeSet(0, len(price) - 1)
        
                # Define the decision variables
                model.bidQuantity_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals)
                model.prodH2_kg = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #produced H2
                model.elecCons_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #electrolyzer consumption per kg
                model.elecStandByCons_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #electrolyzer consumption per kg
                # model.elecColdStartUpCons_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #electrolyzer cold startup consumption per kg
                model.elecColdStartUpCost_EUR = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #electrolyzer consumption per kg
                # model.elecHotStartUpCons_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #electrolyzer hot startup consumption per kg                model.comprCons_MW = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) #compressor consumption per kg
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

                # Define the objective function - minimize cost sum within selected timeframe
                model.obj = pyomo.Objective(expr=sum(0.25* price[i] * model.bidQuantity_MW[i] + model.elecColdStartUpCost_EUR[i] for i in model.i), sense=pyomo.minimize)

                # Status constraints and constraining max and min bid quantity 
                #Max power boundary
                model.maxPower_rule = pyomo.Constraint(model.i, rule=lambda model, i:
                                                        model.elecCons_MW[i] <= self.maxPower * model.isRunning[i] + self.standbyCons*model.isStandBy[i] )
                #min power boundary
                model.minPower_rule = pyomo.Constraint(model.i, rule=lambda model, i:
                                                        model.elecCons_MW[i] >= self.minPower * model.isRunning[i]+ self.standbyCons*model.isStandBy[i])
                #only one operational mode
                model.statesExclusivity = pyomo.Constraint(model.i, rule=lambda model, i:
                                                        model.isRunning[i] + model.isIdle[i] + model.isStandBy[i] == 1)
                #transition from off to on state
                model.statesExclusivity_2 = pyomo.Constraint(model.i, rule=lambda model, i:
                                                        model.isColdStarted[i] >= model.isRunning[i] - model.isRunning[i-1]- model.isStandBy[i-1] if i > 0 else pyomo.Constraint.Skip)
                # # first coldstartup not counted
                # model.statesExclusivity_3 = pyomo.Constraint(model.i, rule=lambda model, i:
                #                                         model.isColdStarted[0] == 0 ) 
                #transition from an off-state to a standby-state is not allowed    
                model.statesExclusivity_4 = pyomo.Constraint(model.i, rule=lambda model, i:
                                                        model.isIdle[i-1] + model.isStandBy[i] <= 1 if i > 0 else pyomo.Constraint.Skip)     
                # #sepcify hot startup timestep
                # model.statesExclusivity_5 = pyomo.Constraint(model.i, rule=lambda model, i:
                #                             model.isStandBy[i-1] <= model.isStandBy[i] + model.isHotStarted[i] if i > 0 else pyomo.Constraint.Skip)  
                #minimum runtime constraint
                def minRuntime_rule(model, i):
                    #force the minimum runtime after a start event
                    next_time_periods = {i + offset for offset in range(int(self.minRuntime)) if i + offset < time_periods}
                    return sum(model.isRunning[tt] + model.isStandBy[tt] for tt in next_time_periods) >= len(next_time_periods) * model.isColdStarted[i]
                model.minRuntime_rule = pyomo.Constraint(model.i, rule=minRuntime_rule)       
                
                #minimum downtime constraint
                def minDownTime_rule(model, i):
                    if i == 0:
                        return pyomo.Constraint.Skip
                    previous_time_periods = {i - offset for offset in range(1, int(self.minDowntime) + 1) if i - offset >=0}
                    return len(previous_time_periods) * model.isColdStarted[i] <= sum(model.isIdle[tt] for tt in previous_time_periods)
                model.minDownTime_rule = pyomo.Constraint(model.i, rule=minDownTime_rule)     

                #maximum allowed cold startups within defined time period    
                model.maxColdStartup_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                    sum(model.isColdStarted[i] for i in range(0, time_periods)) <= maxAllowedColdStartups) 

                model.electrolyzerConsumption_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                    model.prodH2_kg[i] == model.elecCons_MW[i]*0.25*self.effElec/self.energyContentH2_LHV*(1-model.isStandBy[i]) )

                model.hydrogenBalance_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                        model.prodH2_kg[i] == model.elecToPlantUse_kg[i] + model.elecToStorage_kg[i])


                model.demandBalance_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                        industry_demand[i] == model.elecToPlantUse_kg[i] + model.storageToPlantUse_kg[i])   

                model.elecColdStartUpCost_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                            model.elecColdStartUpCost_EUR[i] == self.coldStartUpCost * model.isColdStarted[i])
                
                # model.elecColdStartUp_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                #                                             model.elecColdStartUpCons_MW[i] == self.coldStartUpCons * model.isColdStarted[i])

                model.compressorCons_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                            model.comprCons_MW[i] == model.elecToStorage_kg[i] * self.comprCons/self.world.dt)

                model.standByConsumption_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                            model.elecStandByCons_MW[i] == self.standbyCons*model.isStandBy[i])

                model.totalConsumption_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                        model.bidQuantity_MW[i] == model.elecCons_MW[i] + model.comprCons_MW[i]) #model.elecColdStartUpCons_MW[i]) #+ model.elecHotStartUpCons_MW[i]

                # Define Storage constraint
                model.currentSOC_rule = pyomo.Constraint(model.i, rule=lambda model, i:
                                                    model.currentSOC_kg[i] == model.currentSOC_kg[i - 1] + model.elecToStorage_kg[i] - model.storageToPlantUse_kg[i]
                                                    if i > 0 else model.currentSOC_kg[i] == model.elecToStorage_kg[i]  - model.storageToPlantUse_kg[i])  
                
                model.maxSOC_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                                                    model.currentSOC_kg[i] <= self.maxSOC)

                # model.storageFlowRate_rule = pyomo.Constraint(model.i, rule=lambda model, i: 
                #                                         model.storageToPlantUse_kg[i] <= self.maxStorageOutput)  
                # Solve the optimization problem
                opt = SolverFactory("gurobi")  # You can replace this with your preferred solver
                result = opt.solve(model) #tee=True
                print('INFO: Solver status:', result.solver.status)
                print('INFO: Results: ', result.solver.termination_condition)

                # Retrieve the optimal values
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
                isStandBy = [model.isStandBy[i].value for i in model.i]
                isIdle = [model.isIdle[i].value for i in model.i]
                isColdStarted = [model.isColdStarted[i].value for i in model.i]
                return optimalBidamount,elecCons, elecStandByCons, comprCons,  prodH2, elecToPlantUse_kg, elecToStorage_kg, \
                        storageToPlantUse_kg, currentSOC, isRunning, isStandBy, isIdle, isColdStarted

            #setup optimization input data from flexable
            industrialDemandH2 = self.world.industrial_demand[self.name]
            industrialDemandH2 = pd.DataFrame(industrialDemandH2, columns=[self.name])            
            PFC = [round(p, 2) for p in self.world.PFC]
            PFC = pd.DataFrame(PFC, columns=['PFC'])

            #set up timeframe for optimization #TODO
            optTimeframe = 'day' #input("Choose optimization timefrme, day or week : ")
            simulationYear = 2016 #please specify year
            lastDay = 15 #please specify day
            start_of_year = datetime.datetime(year=simulationYear, month=1, day=1)
            date = start_of_year + datetime.timedelta(days=lastDay - 1)
            lastMonth = date.month
            industrialDemandH2['Timestamp'] = pd.date_range(start=f'1/1/{simulationYear}', end=f'{lastMonth}/{lastDay}/{simulationYear} 23:45', freq='15T')            
            PFC['Timestamp'] = pd.date_range(start=f'1/1/{simulationYear}', end=f'{lastMonth}/{lastDay}/{simulationYear} 23:45', freq='15T')

            #initialize empty lists to retreive optimization reults for all optimized timeperiod
            bidQuantity_all = []
            elecCons_all = []
            elecStandByCons_all = []
            comprCons_all = []
            prodH2_all = []
            elecToPlantUse_kg_all = []
            elecToStorage_kg_all = []
            storageToPlantUse_kg_all = []
            currentSOC_all = []
            isRunning_all = []
            isIdle_all = []
            isStandBy_all = []
            isColdStarted_all = []

            #setting optimization timeframe and calling optimization function
            if optTimeframe == "year":
                print('INFO: Optimization is being performed for entire time period')
                time_periods = len(PFC) 
                maxAllowedColdStartups = self.maxAllowedColdStartups/365*lastDay #number of allowed startups within current timeframe
                demand = list(industrialDemandH2[self.name])
                price = list(PFC['PFC'])
                #Perform optimization for entire time period
                optimalBidamount,elecCons,elecStandByCons, comprCons, prodH2, elecToPlantUse_kg, elecToStorage_kg, storageToPlantUse_kg, \
                    currentSOC, isRunning, isStandBy, isIdle, isColdStarted = optimizeH2Prod(price=price, 
                                                                                            industry_demand=demand, 
                                                                                            time_periods = time_periods, 
                                                                                            maxAllowedColdStartups=maxAllowedColdStartups)
                bidQuantity_all.extend(optimalBidamount)                    
                elecCons_all.extend(elecCons)
                elecStandByCons_all.extend(elecStandByCons)        
                comprCons_all.extend(comprCons)
                prodH2_all.extend(prodH2)
                elecToPlantUse_kg_all.extend(elecToPlantUse_kg)
                elecToStorage_kg_all.extend(elecToStorage_kg)
                storageToPlantUse_kg_all.extend(storageToPlantUse_kg)
                currentSOC_all.extend(currentSOC)
                isRunning_all.extend(isRunning)
                isStandBy_all.extend(isStandBy)            
                isIdle_all.extend(isIdle)            
                isColdStarted_all.extend(isColdStarted)            

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
                    optimalBidamount,elecCons,elecStandByCons, comprCons, prodH2, elecToPlantUse_kg, elecToStorage_kg, storageToPlantUse_kg,\
                        currentSOC, isRunning, isStandBy, isIdle, isColdStarted = optimizeH2Prod(price=monthlyIntervalPFC, 
                                                                                                industry_demand=monthlyIntervalDemand, 
                                                                                                time_periods = time_periods, 
                                                                                                maxAllowedColdStartups=maxAllowedColdStartups)
                    #output results
                    bidQuantity_all.extend(optimalBidamount)                    
                    elecCons_all.extend(elecCons)
                    elecStandByCons_all.extend(elecStandByCons)        
                    comprCons_all.extend(comprCons)
                    prodH2_all.extend(prodH2)
                    elecToPlantUse_kg_all.extend(elecToPlantUse_kg)
                    elecToStorage_kg_all.extend(elecToStorage_kg)
                    storageToPlantUse_kg_all.extend(storageToPlantUse_kg)
                    currentSOC_all.extend(currentSOC)
                    isRunning_all.extend(isRunning)
                    isStandBy_all.extend(isStandBy)            
                    isColdStarted_all.extend(isColdStarted)  

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
                    optimalBidamount,elecCons,elecStandByCons, comprCons, prodH2, elecToPlantUse_kg, elecToStorage_kg, storageToPlantUse_kg, \
                        currentSOC, isRunning, isStandBy, isIdle, isColdStarted = optimizeH2Prod(price=weeklyIntervalPFC, 
                                                                                                industry_demand=weeklyIntervalDemand, 
                                                                                                time_periods = time_periods, 
                                                                                                maxAllowedColdStartups=maxAllowedColdStartups)
                    
                    #output results
                    bidQuantity_all.extend(optimalBidamount)                    
                    elecCons_all.extend(elecCons)
                    elecStandByCons_all.extend(elecStandByCons)        
                    comprCons_all.extend(comprCons)
                    prodH2_all.extend(prodH2)
                    elecToPlantUse_kg_all.extend(elecToPlantUse_kg)
                    elecToStorage_kg_all.extend(elecToStorage_kg)
                    storageToPlantUse_kg_all.extend(storageToPlantUse_kg)
                    currentSOC_all.extend(currentSOC)
                    isRunning_all.extend(isRunning)
                    isStandBy_all.extend(isStandBy)            
                    isIdle_all.extend(isIdle)            
                    isColdStarted_all.extend(isColdStarted)   

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
                    
                    #Perform optimization for each day
                    optimalBidamount,elecCons,elecStandByCons, comprCons, prodH2, elecToPlantUse_kg, elecToStorage_kg, storageToPlantUse_kg, \
                    currentSOC, isRunning, isStandBy, isIdle, isColdStarted = optimizeH2Prod(price=dailyIntervalPFC, 
                                                                                            industry_demand=dailyIntervalDemand, 
                                                                                            time_periods = time_periods, 
                                                                                            maxAllowedColdStartups=maxAllowedColdStartups)
                    #output results
                    bidQuantity_all.extend(optimalBidamount)                    
                    elecCons_all.extend(elecCons)
                    elecStandByCons_all.extend(elecStandByCons)        
                    comprCons_all.extend(comprCons)
                    prodH2_all.extend(prodH2)
                    elecToPlantUse_kg_all.extend(elecToPlantUse_kg)
                    elecToStorage_kg_all.extend(elecToStorage_kg)
                    storageToPlantUse_kg_all.extend(storageToPlantUse_kg)
                    currentSOC_all.extend(currentSOC)
                    isRunning_all.extend(isRunning)
                    isStandBy_all.extend(isStandBy)            
                    isIdle_all.extend(isIdle)            
                    isColdStarted_all.extend(isColdStarted)    
            
        #exporting optimization results, happens one time then code uses exported csv file for the rest of the simulation
            directory = 'output/{}/Elec_capacities'.format(self.world.scenario)
            if not os.path.exists(directory):
                os.makedirs(directory)
            
            output = {'timestamp': industrialDemandH2['Timestamp'], 
                        'bidQuantity': bidQuantity_all,
                        'electrolyzer_consumption': elecCons_all,
                        'compressor_consumption': comprCons_all,
                        'produced_h2': prodH2_all,
                        'electrolyzer_to_plant_h2': elecToPlantUse_kg_all,
                        'electrolyzer_to_storage_h2': elecToStorage_kg_all,
                        'storage_to_plant_h2': storageToPlantUse_kg_all,
                        'SOC': currentSOC_all,
                        'isRunning': isRunning_all,
                        'isStandBy': isStandBy_all,
                        'isIdle': isIdle_all,
                        'isColdStarted': isColdStarted_all,
                        'PFC': PFC['PFC'],
                        'h2demand': industrialDemandH2[self.name]}
            df = pd.DataFrame(output)
            df.to_csv( directory + '/{}_optimizedBidAmount.csv'.format(self.name), index=True)
            #save results into bid requests
            bidQuantity_demand = bidQuantity_all[t]
            bidsEOM = self.collectBidsEOM(t, bidsEOM, bidQuantity_demand)
        return bidsEOM



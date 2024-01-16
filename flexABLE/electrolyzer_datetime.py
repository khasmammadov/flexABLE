from .auxFunc import initializer
from .bid import Bid
import numpy as np
import pandas as pd 
import pyomo.environ as pyomo
from pyomo.opt import SolverFactory 
import os

class Electrolyzer():
    
    @initializer
    def __init__(self,
                 agent=None,
                 name = 'Elec_x',
                 technology = 'PEM',
                 minPower = 90, #[MW]
                 maxPower = 0.1, #[%] minimum partial load 
                 effElec = 0.7, #electrolyzer efficiency[%]
                 effStrg = 0.90, #Storage efficiency[%]
                 specEnerCons = 0.005, #System Specific energy consumption per m3 H2 [MWh/Nm3]
                 pressElec = 30, #pressure of H2 at the end of electrolyzer [bar]
                 presStorage = 700, #H2 storage pressure [bar]
                 maxSOC = 500, #still unknown
                 minDowntime = 0.5, #hours
                 industry = 'Refining', 
                 world = None,
                 node = None,
                 **kwargs):
        
        self.energyContentH2_kg = 0.03333 #MWh/kg or 
        self.energyContentH2_m3 = 0.003 #MWh/Nm³
        self.minDowntime /= self.world.dt          

        # self.minPower = self.nomPower * self.minLoad
        # self.maxPower = self.nomPower * self.maxLoad
        self.installedCapacity =  100 #MW  
        
        # bids status parameters
        self.dictCapacity = {n:0 for n in self.world.snapshots}
        self.dictCapacity[-1] = 0 #used to avoid key value in minimum downtime condition
        
        # Unit status parameters
        self.sentBids = []
        self.currentDowntime = self.minDowntime # Keeps track of the electrolyzer if it reached the minimum shutdown time
        self.currentStatus = 0  # 0 means the electrolyzer is currently off, 1 means it is on
        
    #For the production of 1kg of hydrogen, about 9 kg of water and 60kWh of electricity are consumed(Rievaj, V., Gaňa, J., & Synák, F. (2019). Is hydrogen the fuel of the future?)
    # manages the available capacity, energy storage (SOC), energy cost, and tracks the success of the market. 
    def step(self): 
        self.dictCapacity[self.world.currstep] = 0 #It initializes the available capacity at the current time step to zero.
        for bid in self.sentBids: 
            if 'demandEOM' in bid.ID: #If the bid's ID contains the substring 'demandEOM', it increases the available capacity at the current time step
                self.dictCapacity[self.world.currstep] -= bid.confirmedAmount

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
                                price = 300 #self.world.PFC[t], #offered price is PFC 
                                amount = bidQuantity_demand,
                                status = "Sent",
                                bidType = "Demand",
                                node = self.node))
            return bidsEOM

    # calculation EOM bid
    def calculateBidEOM(self, t):
        bidsEOM = []
        if os.path.exists('output/optimizedBidAmount.csv'):
            optimalBidAmount_all = pd.read_csv("output/optimizedBidAmount.csv")
            bidQuantity_demand=optimalBidAmount_all["bidQuantity"][t] 
            bidsEOM = self.collectBidsEOM(t, bidsEOM, bidQuantity_demand) 
        else: 
            #two different schenarios based on user input are possible
            #1 regular production means, energy purchase should cover production demand at each timestep
            #2 flexible production means the the production and respective energy purchase can be scheduled for the cheapest electricity time
            
            #TODO: set up electrolyzer parameters here
            
            #set up user input variables
            simulationYear = 2016
            lastMonth = 1 #input("Please input simulation end month: ") #will get from scenarios 
            lastDay = 28 #input("Please input simulation end day: ") #will get from scenarios 
            production_mode = '2' #input("Choose optimization mode, 1 for regular production 2 for flexible production: ")
            optTimeframe = 'week' #input("Choose optimization timefrme, day or week : ")
            
            #setup optimization input values
            industrialDemandH2 = self.world.industrial_demand
            PFC = [round(p, 2) for p in self.world.PFC]
            PFC = pd.DataFrame(PFC, columns=['PFC']) 
            industrialDemandH2['Timestamp'] = pd.date_range(start=f'1/1/{simulationYear}', end=f'{lastMonth}/{lastDay}/{simulationYear} 23:45', freq='15T')
            PFC['Timestamp'] = pd.date_range(start=f'1/1/{simulationYear}', end=f'{lastMonth}/{lastDay}/{simulationYear} 23:45', freq='15T')
            
            # Calculate the maxSOC - Max SOC represents calculated  cumulative max total weekly or daily demand
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

            # Defining optimization function       
            def  optimizeH2Prod(price, industry_demand, production_mode):
                model = pyomo.ConcreteModel()
                model.i = pyomo.RangeSet(0, len(price)-1)

                # Define the decision variables
                model.bidQuantity = pyomo.Var(model.i, domain=pyomo.NonNegativeReals)
                model.SOC = pyomo.Var(model.i) 
                
                # Define the objective function - minimize cost sum within selected timeframe
                model.obj = pyomo.Objective(expr=sum(price[i] * model.bidQuantity[i] for i in model.i), sense=pyomo.minimize)
                
                # Define SOC constraints based on selected production mode
                if production_mode == '1': #regular
                    print('INFO: Regular production mode is selected')
                    model.currentSOC = pyomo.Constraint(model.i, rule=lambda model, i:
                                                        model.SOC[i] == model.SOC[i - 1] + model.bidQuantity[i] - industry_demand[i]
                                                        if i > 0 else model.SOC[i] == model.bidQuantity[i] - industry_demand[i])   #for initial timestep at each optimization cycle
                    model.maxSOC = pyomo.Constraint(model.i, rule=lambda model, i: model.SOC[i] <= maxSOC)
                
                elif production_mode == '2': #flexible
                    print('INFO: Flexible production mode is selected')
                    model.currentSOC = pyomo.Constraint(model.i, rule=lambda model, i:
                                                        model.SOC[i] == model.SOC[i - 1] + model.bidQuantity[i] - industry_demand[i]
                                                        if i > 0 else model.SOC[0] >= industry_demand[0])   #for initial timestep at each optimization cycle
                    model.totalDemand = pyomo.Constraint(expr=sum(model.bidQuantity[i] for i in model.i) == sum(industry_demand[i] for i in model.i)) #clarify unit, power/energy conversation

                # Demand should be covered at each step 
                model.demandCoverage_i = pyomo.Constraint(model.i, rule=lambda model, i: model.SOC[i] >= industry_demand[i]) #clarify unit, power/energy conversation
                
                # Max installed capacity constraint 
                model.maxPower = pyomo.Constraint(model.i, rule=lambda model, i: model.bidQuantity[i] <= self.installedCapacity)

                # Solve the optimization problem
                opt = SolverFactory("gurobi")  # You can replace this with your preferred solver
                result = opt.solve(model)
                print('INFO: Solver status:', result.solver.status)
                print('INFO: Results: ', result.solver.termination_condition)

                # Retrieve the optimal values
                optimalBidAmount = [model.bidQuantity[i].value for i in model.i]
                return optimalBidAmount

            optimalBidAmount_all = [] #optimization reults for all optimized days
            #setting optimization modes and calling optimization function
            if optTimeframe == "week":
                print('INFO: Weekly optimization is being performed')
                # find weeks from timestamp
                industrialDemandH2['Week'] = industrialDemandH2['Timestamp'].dt.isocalendar().week
                PFC['Week'] = PFC['Timestamp'].dt.isocalendar().week
                unique_weeks = industrialDemandH2['Week'].unique()
                for week in unique_weeks:
                    # Extract weekly data for the current week
                    weeklyIntervalDemand = industrialDemandH2[industrialDemandH2['Week'] == week]
                    weeklyIntervalDemand = list(weeklyIntervalDemand['industry'])
                    weeklyIntervalPFC = PFC[PFC['Week'] == week]
                    weeklyIntervalPFC = list(weeklyIntervalPFC['PFC'])
                    #Perform optimization for each week
                    optimalBidamount = optimizeH2Prod(price=weeklyIntervalPFC, industry_demand=weeklyIntervalDemand, production_mode=production_mode)
                    optimalBidAmount_all.extend(optimalBidamount)
            elif optTimeframe == "day":
                print('INFO: Daily optimization is being performed')
                # find days from timestamp
                industrialDemandH2['Date'] = industrialDemandH2['Timestamp'].dt.date
                PFC['Date'] = PFC['Timestamp'].dt.date
                unique_days = industrialDemandH2['Date'].unique()
                for day in unique_days:
                    # Extract data for the current day
                    dailyIntervalDemand = industrialDemandH2[industrialDemandH2['Date'] == day]
                    dailyIntervalDemand = list(dailyIntervalDemand['industry'])
                    dailyIntervalPFC = PFC[PFC['Date'] == day]
                    dailyIntervalPFC = list(dailyIntervalPFC['PFC'])
                    #Perform optimization for each day
                    optimalBidamount = optimizeH2Prod(price=dailyIntervalPFC, industry_demand=dailyIntervalDemand, production_mode=production_mode)
                    optimalBidAmount_all.extend(optimalBidamount)
            
            #exporting optimization results, happens one time then code uses exported csv file for the rest of the simulation
            data = {'timestamp': industrialDemandH2['Timestamp'], 'bidQuantity': optimalBidAmount_all }
            df = pd.DataFrame(data)
            df.to_csv('output/optimizedBidAmount.csv', index=False)
            
            #save results into bid request
            bidQuantity_demand = optimalBidAmount_all[t]
            bidsEOM = self.collectBidsEOM(t, bidsEOM, bidQuantity_demand)
        return bidsEOM
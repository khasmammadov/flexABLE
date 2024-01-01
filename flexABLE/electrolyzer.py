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
                 nomPower = 90, #[MW]
                 minLoad = 0.1, #[%] minimum partial load 
                 maxLoad = 1.2, #[%] max partial load
                 effElec = 0.7, #electrolyzer efficiency[%]
                 effStrg = 0.90, #Storage efficiency[%]
                 specEnerCons = 0.005, #System Specific energy consumption per m3 H2 [MWh/Nm3]
                 pressElec = 30, #pressure of H2 at the end of electrolyzer [bar]
                 presStorage = 700, #H2 storage pressure [bar]
                 opsCost = 10, #[Euro] cost of storing 1m3 H2
                 world = None,
                 node = None,
                 **kwargs):
        
        self.energyContentH2_kg = 0.03333 #MWh/kg or 
        self.energyContentH2_m3 = 0.003 #MWh/Nm³

        self.minPower = self.nomPower * self.minLoad
        self.maxPower = self.nomPower * self.maxLoad
        self.installedCapacity =  100 #MW  
        
        # bids status parameters
        self.dictCapacity = {n:0 for n in self.world.snapshots}
        self.dictCapacity[-1] = 0 #used to avoid key value in minimum downtime condition
        
        # Unit status parameters
        self.sentBids = []

# manages the available capacity, energy storage (SOC), energy cost, and tracks the success of the market. 
    def step(self): 
        self.dictCapacity[self.world.currstep] = 0 #It initializes the available capacity at the current time step to zero.
        for bid in self.sentBids: 
            if 'demandEOM' in bid.ID: #If the bid's ID contains the substring 'demandEOM', it increases the available capacity at the current time step
                self.dictCapacity[self.world.currstep] = (-bid.amount) #since demand values are recorded as negative in simulation, addition is done through subtraction          

#clarify
    def feedback(self, bid):
        self.sentBids.append(bid)
        
# generate and return a list of bids based on the specified market type ("EOM," or "negCRMDemand") and the current time step t
    def requestBid(self, t, market="EOM"):
        bids = []
        if market == "EOM":
            bids.extend(self.calculateBidEOM(t))
        # elif market == "negCRMDemand":
        #     bids.extend(self.calculatingBids_CRM_neg(t))
        return bids

    def collectBidsEOM(self, t, bidsEOM, bidQuantity_demand):
            bidsEOM.append(Bid(issuer = self,
                                ID = "{}_demandEOM".format(self.name),
                                price = self.world.PFC[t],
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
            production_mode = input("Choose optimization mode, 1 for regular production 2 for flexible production: ") 
            #followings are to avoid pyomo problems, the inputs form flexable saved to respective variables to be used within optimization cycle            

            industry_demand = list(self.world.industrial_demand["industry"])
            price = list([round(p, 2) for p in self.world.PFC])
            foresight = int(24/0.25) #24 hours, optimization timeframe
            
            # # Calculate the maxSOC - highest daily or weekly (within selected simulation timeframe) total demand value in demand
            interval_count = len(price) // foresight
            interval_sums=[] 
            for interval in range(interval_count):
                start_idx = interval * foresight #start point for time interval
                end_idx = (interval + 1) * foresight #start point for time interval
                interval_sums.append(sum(industry_demand[start_idx:end_idx]))
            maxSOC = max(interval_sums)

            # Defining optimization function       
            def  optimizeH2Prod(price, industry_demand, production_mode):
                model = pyomo.ConcreteModel()
                model.i = pyomo.RangeSet(0, len(price)-1)

                # Define the decision variables
                model.bidQuantity = pyomo.Var(model.i, domain=pyomo.NonNegativeReals)
                model.SOC = pyomo.Var(model.i) 
                
                # Define the objective function - minimize cost sum within selected timeframe
                model.obj = pyomo.Objective(expr=sum(price[i] * model.bidQuantity[i] for i in model.i), sense=pyomo.minimize)
                
                # Define SOC constraints
                if production_mode == '1': #regular
                    model.currentSOC = pyomo.Constraint(model.i, rule=lambda model, i:
                                                        model.SOC[i] == model.SOC[i - 1] + model.bidQuantity[i] - industry_demand[i]
                                                        if i > 0 else model.SOC[i] == model.bidQuantity[i] - industry_demand[i])   #for initial timestep at each optimization cycle
                    model.maxSOC = pyomo.Constraint(model.i, rule=lambda model, i: model.SOC[i] <= maxSOC)
                
                elif production_mode == '2': #flexible
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
                print(result.solver.status)
                print(result.solver.termination_condition)

                # Retrieve the optimal values
                optimalBidAmount = [model.bidQuantity[i].value for i in model.i]
                return optimalBidAmount
            
            optimalBidAmount_all = [] #optimization reults for all optimized days
            # price_all = []
            for interval in range(interval_count):
                start_idx = interval * foresight #start point for time interval
                end_idx = (interval + 1) * foresight #start point for time interval
                interval_industrial_demand = industry_demand[start_idx:end_idx]
                interval_PFC = price[start_idx:end_idx] #setting intervals for price

                # Perform optimization for the current interval
                optimalBidAmount = optimizeH2Prod(price=interval_PFC, industry_demand=interval_industrial_demand, production_mode = production_mode)
                optimalBidAmount_all.extend(optimalBidAmount)

            #exporting optimization results, happens one time then code uses exported csv file for the rest of the simulation
            data = {'bidQuantity': optimalBidAmount_all}
            df = pd.DataFrame(data)
            df.to_csv('output/optimizedBidAmount.csv', index=False)
            
            #save results into bid request
            bidQuantity_demand = optimalBidAmount_all[t]
            bidsEOM = self.collectBidsEOM(t, bidsEOM, bidQuantity_demand)
        return bidsEOM
    
    #testing github
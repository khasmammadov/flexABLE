from .auxFunc import initializer
from .bid import Bid
import numpy as np
import pandas as pd 
import pyomo.environ as pyomo
import os
from pyomo.opt import SolverFactory 

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
                 minDowntime = 1, #[hr] minimum downtime electrolyzer should be shut down before being turned on again
                 opsCost = 10, #[Euro] cost of storing 1m3 H2
                 world = None,
                 node = None,
                 **kwargs):
        
        self.energyContentH2_kg = 0.03333 #MWh/kg or 
        self.energyContentH2_m3 = 0.003 #MWh/Nm³

        self.minPower = self.nomPower * self.minLoad
        self.maxPower = self.nomPower * self.maxLoad

        # Following was added to consider dt 15 mins
        # self.minDowntime /= self.world.dt          
        
        # bids status parameters
        self.dictSOC = {n:0 for n in self.world.snapshots} #SOC, available energy content of H2
        self.dictSOC[0] = 0
        self.dictCapacity = {n:0 for n in self.world.snapshots}
        self.dictCapacity[-1] = 0 #used to avoid key value in minimum downtime condition
        # self.confQtyCRM_neg = {n:0 for n in self.world.snapshots}
        
        # Unit status parameters
        self.sentBids = []
        # self.currentDowntime = self.minDowntime # Keeps track of the electrolyzer if it reached the minimum shutdown time
        # self.currentStatus = 0  # 0 means the electrolyzer is currently off, 1 means it is on
        
        # #Find maxSOC - highest daily (or selected timeframe) demand throughout year
        # foresight = int(24/self.world.dt) #daily
        # demand_intervals = len(self.world.industrial_demand["industry"]) // foresight
        # interval_sums=[]
        # for interval in range(demand_intervals):
        #     start_idx = interval * foresight #start point for time interval
        #     end_idx = (interval + 1) * foresight #start point for time interval
        #     interval_sums.append(sum(self.world.industrial_demand["industry"][start_idx:end_idx])) #[sum(industry_demand[i:i+foresight]) for i in range(0, len(industry_demand), foresight) if i + foresight <= len(price)]
        # self.maxSOC = max(interval_sums) 
        # print(self.maxSOC, "maxSOC")

# manages the available capacity, energy storage (SOC), energy cost, and tracks the success of the market. 
    def step(self): 
        self.dictCapacity[self.world.currstep] = 0 #It initializes the available capacity at the current time step to zero.
        for bid in self.sentBids: 
            if 'demandEOM' in bid.ID: #If the bid's ID contains the substring 'demandEOM', it increases the available capacity at the current time step
                self.dictCapacity[self.world.currstep] -= bid.confirmedAmount #since demand values are recorded as negative in simulation, addition is done through subtraction
            print(self.dictCapacity[self.world.currstep], 'self.dictCapacity[self.world.currstep]')
            # elif "_CRMNegDem" in bid.ID: #CRM negative demand bid
            #     self.dictCapacity[self.world.currstep] -= bid.confirmedAmount                

        self.sentBids=[]
        # if self.world.currstep < len(self.world.snapshots) - 1: #all simulation except the last
        #     if self.dictCapacity[self.world.currstep] < 0: #demand 
        #         self.dictSOC[self.world.currstep + 1] = (self.dictSOC[self.world.currstep] - (self.dictCapacity[self.world.currstep] * self.world.dt)) 
        # else: #If the current time step is the last step sets last SOC to initial starting SOC
        #     if self.dictCapacity[self.world.currstep] < 0:
        #         self.dictSOC[0] += -self.dictCapacity[self.world.currstep] * self.world.dt
                
#The purpose of following method is to provide feedback on the status of a bid
    def feedback(self, bid):
        if bid.status == "Confirmed":
            if 'CRMNegDem' in bid.ID:
                self.confQtyCRM_neg[self.world.currstep] = bid.confirmedAmount
        elif bid.status =="PartiallyConfirmed":
            if 'CRMNegDem' in bid.ID:
                self.confQtyCRM_neg[self.world.currstep] = bid.confirmedAmount
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
        if os.path.exists("optimizedBidAmount.csv"):
            optimalBidAmount_all = pd.read_csv("optimizedBidAmount.csv")
            if (optimalBidAmount_all["bidQuantity"][t] is not None):
                #summarize BID OEM
                bidQuantity_demand=optimalBidAmount_all["bidQuantity"][t] 
                bidsEOM = self.collectBidsEOM(t,bidsEOM, bidQuantity_demand) 
                print(bidsEOM, "bidsEOM")
        else: 
            industry_demand = self.world.industrial_demand["industry"]
            price = self.world.PFC
            foresight = int(24/self.world.dt)  
            # Calculate the maxSOC 
            demand_intervals = len(industry_demand) // foresight
            days = len(price) // foresight
            interval_sums=[]
            for interval in range(days):
                start_idx = interval * foresight #start point for time interval
                end_idx = (interval + 1) * foresight #start point for time interval
                interval_sums.append(sum(industry_demand[start_idx:end_idx])) #[sum(industry_demand[i:i+foresight]) for i in range(0, len(industry_demand), foresight) if i + foresight <= len(price)]
            maxSOC = max(interval_sums)
            
            # Defining optimization function       
            def  optimizeH2Prod(price, industry_demand):
                model = pyomo.ConcreteModel()
                model.i = pyomo.RangeSet(0, len(price) - 1)

                # Define the decision variables
                model.bidQuantity = pyomo.Var(model.i, domain=pyomo.NonNegativeReals)
                model.SOC = pyomo.Var(model.i, domain=pyomo.NonNegativeReals) 
                
                # Define the objective function
                model.obj = pyomo.Objective(expr=sum(price[i] * model.bidQuantity[i] for i in model.i), sense=pyomo.minimize)
                
                # Define initial bid constraints, first bid always made to cover demand
                model.initialBid = pyomo.Constraint(model.i, rule=lambda model, i: model.bidQuantity[0] >= industry_demand[0])
                
                # Define SOC constraints
                model.currentSOC = pyomo.Constraint(model.i, rule=lambda model, i:
                    model.SOC[i] == model.SOC[i - 1] + model.bidQuantity[i] - industry_demand[i]
                    if i > 0 else model.SOC[i] ==  model.bidQuantity[i])   #for initial timestep at each optimization cycle

                # Demand should be covered at each step 
                model.demand = pyomo.Constraint(model.i, rule=lambda model, i: model.SOC[i] >= industry_demand[i])

                # maxSOC constraint
                model.maxSOC = pyomo.Constraint(expr=sum(model.bidQuantity[i] for i in model.i) <= maxSOC)

                # Solve the optimization problem
                opt = SolverFactory("glpk")  # You can replace this with your preferred solver
                result = opt.solve(model)
                
                # Retrieve the optimal values
                optimalBidAmount = [model.bidQuantity[i].value for i in model.i]
                print(optimalBidAmount,len(model.bidQuantity), "optimalBidAmount")
                return optimalBidAmount
            
            optimalBidAmount_all = []
            days = len(price) // foresight
            for interval in range(days):
                start_idx = interval * foresight #start point for time interval
                end_idx = (interval + 1) * foresight #start point for time interval
                interval_industrial_demand = industry_demand[start_idx:end_idx]
                interval_industrial_demand = interval_industrial_demand.reset_index(drop=True)
                interval_PFC = price[start_idx:end_idx] #setting intervals for price
                
                # Perform optimization for the current interval
                optimalBidAmount = optimizeH2Prod(price=interval_PFC, industry_demand=interval_industrial_demand)
                optimalBidAmount_all.extend(optimalBidAmount)
                print(optimalBidAmount_all, len(optimalBidAmount_all), "optimalBidAmount_all")

                #exporting optimization results, happens one time then code uses exported csv file for the rest of the simulation
                data = {'bidQuantity': optimalBidAmount_all}
                df = pd.DataFrame(data)
                df.to_csv('optimizedBidAmount.csv', index=False)
            
            bidQuantity_demand = optimalBidAmount_all[t]
            bidsEOM = self.collectBidsEOM(t, bidsEOM, bidQuantity_demand)
        return bidsEOM

# #Industrial plants onlu participare in CRM using its H2 system capacity
#     def calculatingBids_CRM_neg(self, t):
#         bidsCRM = []
#         industry_demand = self.world.industrial_demand["industry"]
#         foresight = int(24/self.world.dt) #weekly
#         # Calculate the maxSOC 
#         demand_intervals = len(industry_demand) // foresight
#         interval_sums = [sum(industry_demand[i:i+foresight]) for i in range(0, len(industry_demand), foresight)]
#         maxSOC = max(interval_sums)
#         availablePower_H2_storage = 33 #min(max((self.maxSOC - abs(self.dictSOC[t])) / self.effElec / self.effStrg / self.world.dt, 0),self.maxPower)
#         if (availablePower_H2_storage >= self.world.minBidCRM and  #market minimum requirement,if greater than 1MWh
#             self.dictSOC[t] < maxSOC):
#             bidQtyCRM_neg = availablePower_H2_storage
#             bidsCRM.append(Bid(issuer = self,
#                                ID = "{}_CRMNegDem".format(self.name),
#                                price = 0,
#                                amount = bidQtyCRM_neg,
#                                energyPrice = 0, #zero energy price offer for charging in CRM
#                                status = "Sent",
#                                bidType = "Supply"))

#         else: #unsuccesful bid, sets energy price and amount to 0
#             bidsCRM.append(Bid(issuer = self,
#                                ID = "{}_CRMNegDem".format(self.name),
#                                price = 0,
#                                amount = 0,
#                                energyPrice = 0,
#                                status = "Sent",
#                                bidType = "Supply"))
#         return bidsCRM

 # -*- coding: utf-8 -*-
from .auxFunc import initializer
from .bid import Bid


class Electrolyzer():
    @initializer
    def __init__(self,
                agent=None,
                name = 'Elec_x',
                technology = 'PEM',
                minLoad = 0.1, #[%]
                installedCapacity = 100, #[MW] max power 
                effElec = 0.7, #electrolyzer efficiency[%]
                minDowntime = 0.5, #minimum standby time hours
                minRuntime = 1, #hours
                coldStartUpCost = 50, # Euro per MW installed capacity
                maxAllowedColdStartups = 3000, #yearly allowed max cold startups
                standbyCons = 0.05, #% of installed capacity 
                comprCons = 0.0012, #MWh/kg  compressor specific consumptin
                maxSOC = 2000, #Kg
                maxStorageOutput = 800, #[kg/hr] max flow output of hydrogen storage 
                industry = 'Refining', 
                world = None,
                node = None,
                 **kwargs):
        
        self.energyContentH2_LHV = 0.03333 #MWh/kg or lower heating value of H2
        #adjusting hourly values for 15 min simulation interval
        self.minDowntime /= self.world.dt     
        self.minPower = self.installedCapacity * self.minLoad #[MW]
        self.standbyCons *= self.installedCapacity 
        self.shutdownAfterInactivity = 8
        # bids status parameters
        self.dictCapacity = {n:0 for n in self.world.snapshots}
        self.dictCapacity[-1] = 0 #used to avoid key value in minimum downtime condition
        
        # Unit status parameters
        self.sentBids = []
        self.currentDowntime = self.minDowntime # Keeps track of the electrolyzer if it reached the minimum shutdown time
        self.currentStatus = 0  # 0 means the electrolyzer is currently off, 1 means it is on

# manages the available capacity, energy storage (SOC), energy cost, and tracks the success of the market. 
    def step(self): 
        self.dictCapacity[self.world.currstep] = 0 #It initializes the available capacity at the current time step to zero.
        for bid in self.sentBids: #why only EOM calculated here??
            if 'demandEOM' in bid.ID: 
                self.dictCapacity[self.world.currstep] -= bid.confirmedAmount             
        
        # Checks if the Electrolyzer is shutdown and whether it can start-up
        if self.currentStatus == 0:  
            if self.dictCapacity[self.world.currstep - 1] == 0: # Adds to the counter of the number of steps it was off
                self.currentDowntime += 1
            elif self.currentDowntime >= self.minDowntime: # Electrolyzer can turn on
                if abs(self.dictCapacity[self.world.currstep]) >= self.minPower:
                    self.currentDowntime = 0
                    self.currentStatus = 1
                else:
                    self.dictCapacity[self.world.currstep] = 0
                    self.currentStatus = 0
        else: #currentStatus == 1
            if abs(self.dictCapacity[self.world.currstep]) < self.minPower: #self.minPower:
                self.currentStatus = 0
                self.currentDowntime = 1
            else:
                self.currentStatus = 1
        self.sentBids=[]
    
    #clarify
    def feedback(self, bid):
        if bid.status == "Confirmed":
            if 'CRMNegDem' in bid.ID:
                self.confQtyCRM_neg[self.world.currstep] = bid.confirmedAmount
            
        elif bid.status =="PartiallyConfirmed":
            if 'CRMNegDem' in bid.ID:
                self.confQtyCRM_neg[self.world.currstep] = bid.confirmedAmount
        self.sentBids.append(bid)
    # def feedback(self, bid):
    #     self.sentBids.append(bid)
        
    def requestBid(self, t, market="EOM"):
        bids = []
        if market == "EOM":
            print( 'Im in requestBid ')
            bids.extend(self.calculateBidEOM(t))

# calculation EOM bid
    def calculateBidEOM(self, t):
        bidsEOM = []
        industrial_demand = dict(self.world.industrial_demand[self.name])
        print(industrial_demand, 'industrial_demand')
        if (self.currentStatus) or (not(self.currentStatus) and (self.currentDowntime >= self.minDowntime)): #either currently on or has been off for at least the minimum downtime
                elecConsumption = industrial_demand[t] * self.energyContentH2_LHV / self.effElec / self.world.dt
                print(elecConsumption, 'elecConsumption')
        elif not(self.currentStatus) and (self.currentDowntime <= self.shutdownAfterInactivity):
                elecConsumption = industrial_demand[t] * self.energyContentH2_LHV / self.effElec / self.world.dt + self.standbyCons
        elif self.currentDowntime >= self.shutdownAfterInactivity:
            elecConsumption = 0  
        print(elecConsumption, 'elecConsumption')
        bidQuantity_demand = elecConsumption
        
        if (bidQuantity_demand >= self.world.minBidEOM ): #market minimum requirement,if greater than 1MWh
                bidsEOM.append(Bid(issuer = self,
                                ID = "{}_demandEOM".format(self.name),
                                price = 300,
                                amount = bidQuantity_demand,
                                status = "Sent",
                                bidType = "Demand",
                                node = self.node))
        return bidsEOM

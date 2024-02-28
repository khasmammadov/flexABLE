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
                industry = 'Refining', 
                world = None,
                node = None,
                 **kwargs):
        
        self.energyContentH2_LHV = 0.03333 #MWh/kg or lower heating value of H2
        #adjusting hourly values for 15 min simulation interval
        self.minDowntime /= self.world.dt     
        self.minPower = self.installedCapacity * self.minLoad #[MW]
        self.standbyCons *= self.installedCapacity 
        
        # bids status parameters
        self.dictCapacity = {n:0 for n in self.world.snapshots}
        self.dictCapacity[-1] = 0 
        
        # Unit status parameters
        self.sentBids = []

    def step(self): 
        # self.dictCapacity[self.world.currstep] = 0 
        for bid in self.sentBids: 
            if 'demandEOM' in bid.ID: 
                self.dictCapacity[self.world.currstep] = bid.confirmedAmount      
                print(self.dictCapacity[self.world.currstep], 'self.dictCapacity[self.world.currstep]')       
    
    def feedback(self, bid):
        self.sentBids.append(bid)
        
    def requestBid(self, t, market="EOM"):
        bids = []
        if market == "EOM":
            bids.extend(self.calculateBidEOM(t))
        return bids

# calculation EOM bid
    def calculateBidEOM(self, t):
        bidsEOM = []
        industrial_demand = dict(self.world.industrial_demand[self.name])
        if industrial_demand[t] != 0: 
            elecConsumption = industrial_demand[t] * self.energyContentH2_LHV / self.effElec / self.world.dt
            if elecConsumption > self.installedCapacity:
                print('Selected installed capacity is not sufficient for covering demand. Please increase electrolyzer capacity value')   
        else : #industrial_demand[t] == 0
            elecConsumption = self.standbyCons
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

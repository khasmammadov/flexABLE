 # -*- coding: utf-8 -*-
from .auxFunc import initializer
from .bid import Bid
import numpy as np


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
                 world = None,
                 node = None,
                 **kwargs):
        
        #converting H2 storage volume to energy value
        self.compression = self.pressElec/self.presStorage #compression ration between electrolyzer pressure and storage pressure
        self.maxSOC = (self.H2StrgCap / self.compression / self.effStrg) * self.specEnerCons   #maximum H2 storage capacity in energy value MWh
        
        self.minPower = self.nomPower * self.minLoad
        self.maxPower = self.nomPower * self.maxLoad

        # Following was added to consider dt 15 mins
        self.minDowntime /= self.world.dt          
        
        # bids status parameters
        self.dictSOC = {n:0 for n in self.world.snapshots} #SOC, available energy content of H2
        self.dictSOC[0] = 0
        self.dictH2volume = {n:0 for n in self.world.snapshots} #hydrogen volume at the end of electrolyzer, without compression
        self.dictCapacity = {n:0 for n in self.world.snapshots}
        self.dictCapacity[-1] = 0 #used to avoid key value in minimum downtime condition
        self.confQtyCRM_neg = {n:0 for n in self.world.snapshots}
        
        # Unit status parameters
        self.marketSuccess = [0]
        self.sentBids = []
        self.currentDowntime = self.minDowntime # Keeps track of the electrolyzer if it reached the minimum shutdown time
        self.currentStatus = 0  # 0 means the electrolyzer is currently off, 1 means it is on
        # self.foresight = int(336/self.world.dt) #the number of time steps ahead the code should consider when calculating the average price, here for 1 week

# manages the available capacity, energy storage (SOC), energy cost, and tracks the success of the market. 
    def step(self): 
        self.dictCapacity[self.world.currstep] = 0 #It initializes the available capacity at the current time step to zero.
        for bid in self.sentBids: #why only EOM calculated here??
            if 'demandEOM' in bid.ID: #If the bid's ID contains the substring 'demandEOM', it decreases the available capacity at the current time step
                self.dictCapacity[self.world.currstep] -= bid.confirmedAmount
            elif "_CRMNegDem" in bid.ID:
                self.dictCapacity[self.world.currstep] -= bid.confirmedAmount                

        self.sentBids=[]
        if self.world.currstep < len(self.world.snapshots) - 1: #all simulation except the last
            if self.dictCapacity[self.world.currstep] < 0: #demand 
                self.dictSOC[self.world.currstep + 1] = (self.dictSOC[self.world.currstep] - 
                                                         (self.dictCapacity[self.world.currstep] * self.effElec * self.effStrg * self.world.dt))
                self.dictH2volume[self.world.currstep] = abs(self.dictCapacity[self.world.currstep]) * self.world.dt / self.specEnerCons * self.effStrg * self.compression
 
        else: #If the current time step is the last step sets last SOC to initial starting SOC
            if self.dictCapacity[self.world.currstep] < 0:
                self.dictSOC[0] += -self.dictCapacity[self.world.currstep] * self.effElec * self.effStrg * self.world.dt
                self.dictH2volume[self.world.currstep] = abs(self.dictCapacity[self.world.currstep]) * self.world.dt  / self.specEnerCons * self.effStrg * self.compression
        
        # Checks if the Electrolyzer is shutdown and whether it can start-up
        if self.currentStatus == 0:  #Electrolyzer plant is off
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
        elif market == "negCRMDemand":
            bids.extend(self.calculatingBids_CRM_neg(t))
        return bids

# calculation EOM bid
    def calculateBidEOM(self, t):
        bidsEOM = []
        industrial_demand = dict(self.world.industrial_demand["industry"])
        bidQuantity_demand_H2 = 0
        if self.world.PFC[t] >= self.costTresholdDischr: #h2 use abover certain PFC cost
            if self.dictSOC[t] >= industrial_demand[t] * self.world.dt: #if h2 storage present at current timestep use H2
                self.dictSOC[t] -= industrial_demand[t] / self.effFC * self.world.dt
                print(self.dictSOC[t], 'SOC')
                print(dict(self.world.industrial_demand["industry"])[t] , '1. H2 use when available')
            else:
                bidQuantity_demand_directUse = industrial_demand[t]
                bidQuantity_demand_H2 = 0
                print(dict(self.world.industrial_demand["industry"])[t] , '1. H2 use not available')

        elif self.world.PFC[t] < self.costTresholdDischr and self.world.PFC[t] > self.costTresholdCharge: #direct electricity buying
            bidQuantity_demand_directUse = industrial_demand[t]
            bidQuantity_demand_H2 = 0
            print(dict(self.world.industrial_demand["industry"])[t] , '2. direkt use')
            
        elif self.world.PFC[t] <= self.costTresholdCharge:
            bidQuantity_demand_directUse = industrial_demand[t]
            if  ((self.currentStatus) or (not(self.currentStatus) and (self.currentDowntime >= self.minDowntime)) and #either currently on or has been off for at least the minimum downtime
                self.dictSOC[t] < self.maxSOC): #if reserve is not full
                bidQuantity_demand_H2 = min(max((self.maxSOC - self.dictSOC[t] - 
                                            self.confQtyCRM_neg[t] * self.world.dt) / self.effElec / self.effStrg / self.world.dt, 0),
                                            self.maxPower)
                print(dict(self.world.industrial_demand["industry"])[t] , '3. charging+direct use')              
                
        bidQuantity_demand = bidQuantity_demand_directUse + bidQuantity_demand_H2
        bidPrice_demand = self.world.PFC[t]
        print(bidQuantity_demand, bidPrice_demand, 'bidQuantity_demand +PFC')                

        #summarize BID OEM
        if (bidQuantity_demand >= self.world.minBidEOM ): #market minimum requirement,if greater than 1MWh
                bidsEOM.append(Bid(issuer = self,
                                ID = "{}_demandEOM".format(self.name),
                                price = bidPrice_demand,
                                amount = bidQuantity_demand,
                                status = "Sent",
                                bidType = "Demand",
                                node = self.node))
        return bidsEOM

#Industrial plants onlu participare in CRM using its H2 system capacity
    def calculatingBids_CRM_neg(self, t):
        bidsCRM = []
        availablePower_H2_storage = min(max((self.maxSOC - abs(self.dictSOC[t])) / self.effElec / self.effStrg / self.world.dt, 0),
                                    self.maxPower)
        if (availablePower_H2_storage >= self.world.minBidCRM and  #market minimum requirement,if greater than 1MWh
            self.dictSOC[t] < self.maxSOC):
            bidQtyCRM_neg = availablePower_H2_storage
            print(bidQtyCRM_neg, 'availablePower_H2_storage')
            bidsCRM.append(Bid(issuer = self,
                               ID = "{}_CRMNegDem".format(self.name),
                               price = 0,
                               amount = bidQtyCRM_neg,
                               energyPrice = 0, #zero energy price offer for charging in CRM
                               status = "Sent",
                               bidType = "Supply"))

        else: #unsuccesful bid, sets energy price and amount to 0
            bidsCRM.append(Bid(issuer = self,
                               ID = "{}_CRMNegDem".format(self.name),
                               price = 0,
                               amount = 0,
                               energyPrice = 0,
                               status = "Sent",
                               bidType = "Supply"))
        return bidsCRM
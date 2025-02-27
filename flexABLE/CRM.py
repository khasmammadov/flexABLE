# -*- coding: utf-8 -*-
"""
Created on Mon Apr  20 19:24:32 2020

@author: intgridnb-02
"""
import operator
from .bid import Bid
import logging
from .MarketResults import MarketResults

class CRM():
    """
    This class represents the control reserve market (aFFR and mFFR).
    This class collects the bids from eligible market participants and performs market clearing.
    The market clearing for the CAPACITY is performed on the basis of submitted capacity price.
    The market clearing for the ENERGY is performd on the basis of submitted energy price.
    The used mechaism for the market clearing is "pay as bid".
    
    """
    
    def __init__(self, name, demand = None, world = None):
        self.name = name
        self.world = world
        self.snapshots = self.world.snapshots
        
        if demand == None:
            self.demand = {"posCRMDemand":{t:0 for t in self.snapshots},
                           "negCRMDemand":{t:0 for t in self.snapshots},
                           "posCRMCall":{t:0 for t in self.snapshots},
                           "negCRMCall":{t:0 for t in self.snapshots}}
            
        elif len(demand["posCRMDemand"]) == len(demand["negCRMDemand"]) == len(demand["posCRMCall"]) == len(demand["negCRMCall"]) == len(self.snapshots):
            self.demand = demand
            
        else:
            print("Length of given demand does not match snapshots length!")

        self.bids = {"posCRMDemand":{t:[] for t in range(96)},
                     "negCRMDemand":{t:[] for t in range(96)},
                     "posCRMCall":{t:[] for t in range(96)},
                     "negCRMCall":{t:[] for t in range(96)}}
        
        self.marketResults = {"posCRMDemand":{t:0 for t in range(96)},
                              "negCRMDemand":{t:0 for t in range(96)},
                              "posCRMCall":{t:0 for t in range(96)},
                              "negCRMCall":{t:0 for t in range(96)}}
        
        
    def step(self, t, agents):
        for product in ["posCRMDemand","negCRMDemand"]:
            
            if t % self.world.dtu and product in ["posCRMDemand","negCRMDemand"]:
                self.marketResults[product][t % 96]  = self.marketResults[product][(t % 96) - 1]
                self.bids[product][t % 96] = self.bids[product][(t % 96) - 1]
                
            else:
                self.collectBids(agents, t, product)
                self.marketClearing(t, product)
                
        
    def collectBids(self, agents, t, product):
        self.bids[product][(t % 96)] = []
        
        if product == 'posCRMCall':
            self.bids[product][(t % 96)].extend(self.marketResults['posCRMDemand'][((t % 96) // 16) * 16].confirmedBids)
            
        if product == 'negCRMCall':
            self.bids[product][(t % 96)].extend(self.marketResults['negCRMDemand'][((t % 96) // 16) * 16].confirmedBids)
            
        for agent in agents.values():
            self.bids[product][(t % 96)].extend(agent.requestBid(t, product))
            

    def marketClearing(self, t, product):
        
        if product in ["posCRMDemand", "negCRMDemand"]:
            sortingAttribute = 'price'
        else:
            sortingAttribute = 'energyPrice'
         
        bidsReceived = {"Supply":[],
                        "Demand":[]}
        
        confirmedBids = []
        rejectedBids = []
        partiallyConfirmedBids = []
        
        for b in self.bids[product][(t % 96)]:
            if b.bidType =='InelasticDemand':
                continue
            
            bidsReceived[b.bidType].append(b)
            
        bidsReceived["Supply"].sort(key = operator.attrgetter(sortingAttribute),
                                    reverse = True)
        
        bidsReceived["Demand"].append(Bid(issuer = self,
                                          ID = "IEDt{}".format(t),
                                          price = -3000,
                                          amount = -self.demand[product][t],
                                          status = "Sent",
                                          bidType = "InelasticDemand"))
        
        bidsReceived["Demand"].sort(key = operator.attrgetter(sortingAttribute),
                                    reverse = True)
        
        sum_totalSupply = sum(bidsReceived["Supply"])
        sum_totalDemand = sum(bidsReceived["Demand"])
        
        # =====================================================================
        # The different cases of uniform price market clearing
        # Case 1: The sum of either supply or demand is 0
        # Case 2: Inelastic demand is higher than sum of all supply bids
        # Case 3: Covers all other cases       
        # =====================================================================
        
        #Case 1
        if sum_totalSupply == 0 or sum_totalDemand == 0:
            logging.debug('The sum of either demand offers ({}) or supply '
                          'offers ({}) is 0 at t:{}'.format(sum_totalDemand, sum_totalSupply, t))
            
            result = MarketResults("{}".format(self.name),
                                   issuer = self.name,
                                   confirmedBids = [],
                                   rejectedBids = bidsReceived["Demand"] + bidsReceived["Supply"],
                                   marketClearingPrice = 0,
                                   marginalUnit = "None",
                                   status = "Case1",
                                   timestamp = t)
            
        #Case 2
        elif self.demand[product][t] > sum_totalSupply:
            """
            Since the Inelastic demand is higher than the sum of all supply offers
            all the supply offers are confirmed
            
            The marginal unit is assumed to be the last supply bid confirmed
            """
            
            for b in bidsReceived["Supply"]:
                confirmedBids.append(b)
                b.confirm()
                
            bidsReceived["Demand"][-1].partialConfirm(sum_totalSupply)
            partiallyConfirmedBids.append(bidsReceived["Demand"].pop())
            rejectedBids = list(set(bidsReceived["Supply"] + bidsReceived["Demand"]) - set(confirmedBids))
            marketClearingPrice = getattr(sorted(confirmedBids, key = operator.attrgetter(sortingAttribute))[-1], sortingAttribute)
            
            result = MarketResults("{}".format(self.name),
                                   issuer = self.name,
                                   confirmedBids = confirmedBids,
                                   rejectedBids = rejectedBids,
                                   partiallyConfirmedBids = partiallyConfirmedBids,
                                   marketClearingPrice = marketClearingPrice,
                                   marginalUnit = "None",
                                   status = "Case2",
                                   energyDeficit = self.demand[product][t] - sum_totalSupply,
                                   energySurplus = 0,
                                   timestamp = t)

        #Case 3
        else:
            confirmedBidsDemand = [bidsReceived["Demand"][-1]]
            # The inelastic demand is directly confirmed since the sum of supply energy it is enough to supply it
            bidsReceived["Demand"][-1].confirm()
            confirmedBidsSupply = []
            confQty_demand = bidsReceived["Demand"][-1].amount
            confQty_supply = 0
            currBidPrice_demand = 3000.00
            currBidPrice_supply = -3000.00
    
            while True:
                # =============================================================================
                # Cases to accept bids
                # Case 3.1: Demand is larger than confirmed supply, and the current demand price is
                #         higher than the current supply price, which signals willingness to buy
                # Case 3.2: Confirmed demand is less or equal to confirmed supply but the current 
                #         demand price is higher than current supply price, which means there is still 
                #         willingness to buy and energy supply is still available, so an extra demand
                #         offer is accepted
                # Case 3.3: The intersection of the demand-supply curve has been exceeded (Confirmed Supply 
                #         price is higher than demand)
                # Case 3.4: The intersection of the demand-supply curve found, and the price of both offers
                #         is equal
                
                
                # =============================================================================
                # Case 3.1
                # =============================================================================
                if confQty_demand > confQty_supply and currBidPrice_demand > currBidPrice_supply:
                    try:
                        '''
                        Tries accepting last supply offer since they are reverse sorted
                        excepts that there are no extra supply offers, then the last demand offer
                        is changed into a partially confirmed offer
                        '''
                        
                        confirmedBidsSupply.append(bidsReceived["Supply"].pop())
                        confQty_supply += confirmedBidsSupply[-1].amount
                        currBidPrice_supply = confirmedBidsSupply[-1].price
                        confirmedBidsSupply[-1].confirm()
    
                    except IndexError:
                        confirmedBidsDemand[-1].partialConfirm(confirmedBidsDemand[-1].amount-(confQty_demand - confQty_supply))
                        break
                    
                # =============================================================================
                # Case 3.2
                # =============================================================================
                elif confQty_demand <= confQty_supply and currBidPrice_demand > currBidPrice_supply:
                    try:
                        '''
                        Tries accepting last demand offer since they are reverse sorted
                        excepts that there are no extra demand offers, then the last supply offer
                        is changed into a partially confirmed offer
                        '''

                        confirmedBidsDemand.append(bidsReceived["Demand"].pop())
                        confQty_demand += confirmedBidsDemand[-1].amount
                        currBidPrice_demand = confirmedBidsDemand[-1].price
                        confirmedBidsDemand[-1].confirm()
                        
                    except IndexError:
                        confirmedBidsSupply[-1].partialConfirm(confirmedBidsSupply[-1].amount-(confQty_demand - confQty_supply))
                        break
    
                # =============================================================================
                # Case 3.3    
                # =============================================================================
                elif currBidPrice_demand < currBidPrice_supply:
                    
                    # Checks whether the confirmed demand is greater than confirmed supply
                    if (confQty_supply - confirmedBidsSupply[-1].amount) < (confQty_demand - confirmedBidsDemand[-1].amount):
                        confQty_demand -= confirmedBidsDemand[-1].amount
                        confirmedBidsSupply[-1].partialConfirm(confirmedBidsSupply[-1].amount - (confQty_supply - confQty_demand))
                        bidsReceived["Demand"].append(confirmedBidsDemand.pop())
                        bidsReceived["Demand"][-1].reject()
                        break
    
                    # Checks whether the confirmed supply is greater than confirmed demand
                    elif (confQty_supply - abs(confirmedBidsSupply[-1].amount)) > (confQty_demand - confirmedBidsDemand[-1].amount):
                        confQty_supply -= confirmedBidsSupply[-1].amount
                        confirmedBidsDemand[-1].partialConfirm(confirmedBidsDemand[-1].amount - (confQty_demand - confQty_supply))
                        bidsReceived["Supply"].append(confirmedBidsSupply.pop())
                        bidsReceived["Supply"][-1].reject()
                        break
    
                    # The confirmed supply matches confirmed demand
                    else:
                        break
    
                # =============================================================================
                # Case 3.4
                # =============================================================================
                elif currBidPrice_demand == currBidPrice_supply:
    
                    # Confirmed supply is greater than confirmed demand
                    if confQty_supply > confQty_demand:
                        confirmedBidsSupply[-1].partialConfirm(confirmedBidsSupply[-1].amount - (confQty_supply - confQty_demand))
                        break
    
                    # Confirmed demand is greater than confirmed supply
                    elif confQty_demand > confQty_supply:
                        confirmedBidsDemand[-1].partialConfirm(confirmedBidsDemand[-1].amount - (confQty_demand - confQty_supply))
                        print(confirmedBidsDemand[-1], self.world.currstep, 'confirmedBidsDemand[-1]')
                        confirmedBidsDemand[-1][1] -= (confQty_demand - confQty_supply)
                        print(confirmedBidsDemand[-1][1], self.world.currstep, 'confirmedBidsDemand[-1][1]')
                        break
                        
                    # Confirmed supply and confirmed demand are equal
                    else:
                        break
    
                # Both price and amount for supply and demand are equal, market is cleared
                else:
                    break
            
            
            confirmedBids = confirmedBidsDemand + confirmedBidsSupply
            rejectedBids = list(set(bidsReceived["Supply"] + bidsReceived["Demand"]) - set(confirmedBids))
            marketClearingPrice = getattr(sorted(confirmedBids,key=operator.attrgetter(sortingAttribute))[-1],sortingAttribute)
            marginalUnit = sorted(confirmedBids,key=operator.attrgetter(sortingAttribute))[-1].ID

            result = MarketResults("{}".format(self.name),
                                   issuer = self.name,
                                   confirmedBids = confirmedBids,
                                   rejectedBids = rejectedBids,
                                   partiallyConfirmedBids = partiallyConfirmedBids,
                                   marketClearingPrice = marketClearingPrice,
                                   marginalUnit = marginalUnit,
                                   status = "Case3",
                                   energyDeficit = 0,
                                   energySurplus = 0,
                                   timestamp = t)


        self.marketResults[product][(t % 96)] = result
        
    def feedback(self,award):
        pass

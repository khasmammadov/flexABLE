# -*- coding: utf-8 -*-
"""
Created on Sun Apr  19 15:59:22 2020

@author: intgridnb-02
"""
from loggingGUI import logger, loggerGUI
class Bid(object):
    """
    The bid class is intended to represent a bid object that is offered on a DA-Market
    The minimum amount of energy that could be traded is 0.1 MWh and the price could range
    between -500 €/MWh up to 3000 €/MWh. 
    This does not represent a bid block. Multiple objects of the class bid could be used to define
    a block bid, but 
    """
    def __init__(self,issuer="Not-Issued", ID="Generic", price=0, amount=0, energyPrice=0, status=None, bidType=None):
        self.ID = ID
        self.issuer = issuer
        self.price = price
        self.amount = abs(amount)
        self.confirmedAmount = 0
        self.energyPrice=energyPrice
        if status == None:
            self.status = "Created"
        else:
            self.status = status
        if bidType == None:
            self.bidType = "Supply" if amount > 0 else "Demand"
        else:
            self.bidType = bidType

    def __repr__(self):
        return self.ID

    def __add__(self, other):
        try:
            return Bid(amount=(self.amount + other.amount)).amount  # handle things with value attributes
        except AttributeError:
            return Bid(amount=(self.amount + other)).amount  # but also things without
    __radd__ = __add__
    
    def confirm(self):
        self.status = "Confirmed"
        self.confirmedAmount = self.amount
        
    def partialConfirm(self, confirmedAmount=0):
        self.status = "PartiallyConfirmed"
        if confirmedAmount > self.amount:
            logging.warning("For bid {}, the confirmed amount is greater than offered amount."
                            " Confirmed amount reduced to offered amount."
                            " This could eventually cause imbalance problem.".format(self.ID))
            self.confirmedAmount = self.amount
            
        else:
            self.confirmedAmount= confirmedAmount
            
    def reject(self):
        if 'IED' in self.ID:
            pass
        else:
            self.status = "Rejected"
            self.confirmedAmount = 0
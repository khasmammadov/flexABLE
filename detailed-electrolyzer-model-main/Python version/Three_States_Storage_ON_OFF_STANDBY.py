import pandas as pd 
import pyomo.environ as pyo
from pyomo.opt import SolverFactory 
def optimizeH2Prod(price, industry_demand, time_periods):
    model = pyomo.ConcreteModel('Optimized Electroluzer Bidding')
    model.i = pyomo.RangeSet(0, len(price) - 1)
    model.T = Set()  # Time periods
    model.S = Set()  # Segments

    # Define variables
    model.m = Var(model.T, domain=NonNegativeReals)  # Electricity market
    model.m_in = Var(model.T, domain=NonNegativeReals)  # Bought from electricity market for standby
    model.e = Var(model.T, model.S, domain=NonNegativeReals)  # Electrolyzer consumption for each segment
    model.e_tot = Var(model.T, domain=NonNegativeReals)  # Electrolyzer consumption for each segment
    model.h = Var(model.T, domain=NonNegativeReals)  # Hydrogen production
    model.h_d = Var(model.T, domain=NonNegativeReals)  # Hydrogen production directly to demand
    model.d = Var(model.T, domain=NonNegativeReals)  # Hydrogen sold
    model.c = Var(model.T, domain=NonNegativeReals)  # Compressor consumption
    model.s_in = Var(model.T, domain=NonNegativeReals)  # Hydrogen stored
    model.s_out = Var(model.T, domain=NonNegativeReals)  # Hydrogen used from storage
    model.soc = Var(model.T, domain=NonNegativeReals)  # State of charge of storage (kg)
    model.z_h = Var(model.T, model.S, domain=Binary)  # Specific hydrogen production
    model.z_on = Var(model.T, domain=Binary)  # On electrolyzer
    model.z_off = Var(model.T, domain=Binary)  # Off electrolyzer
    model.z_sb = Var(model.T, domain=Binary)  # Standby electrolyzer
    model.z_start = Var(model.T, domain=Binary)  # Start electrolyzer

    #************************************************************************
    # Objective function
    def objective_rule(model):
        return sum(
            model.m[t] * lambda_M[t, 1]
            + model.d[t] * lambda_H
            - model.m_in[t] * lambda_M_in[t, 1]
            - model.z_start[t] * lambda_start
            for t in model.T
        )
    model.objective = Objective(rule=objective_rule, sense=maximize)

    #************************************************************************
    # Constraints

    # Electricity offer
    def elec_offer_constraint_rule(model, t):
        return model.m[t] == P_W[t] + model.m_in[t] - model.e_tot[t] - model.c[t]
    model.elec_offer_constraint = Constraint(model.T, rule=elec_offer_constraint_rule)

    # Standby power from market
    def standby_power_constraint_rule(model, t):
        return model.m_in[t] <= P_sb * model.z_sb[t]
    model.standby_power_constraint = Constraint(model.T, rule=standby_power_constraint_rule)

    # Total electricity consumption
    def total_elec_consumption_rule(model, t):
        return model.e_tot[t] == sum(model.e[t, s] for s in model.S) + P_sb * model.z_sb[t]
    model.total_elec_consumption_constraint = Constraint(model.T, rule=total_elec_consumption_rule)

    # Hydrogen production
    def hydrogen_production_rule(model, t):
        return model.h[t] == sum(a[s] * model.e[t, s] + b[s] * model.z_h[t, s] for s in model.S)
    model.hydrogen_production_constraint = Constraint(model.T, rule=hydrogen_production_rule)

    # Segment min power boundary
    def segment_min_power_boundary_rule(model, t, s):
        return model.e[t, s] >= P_segments[segments][s] * C_E * model.z_h[t, s]
    model.segment_min_power_boundary_constraint = Constraint(model.T, model.S, rule=segment_min_power_boundary_rule)

    # Segment max power boundary
    def segment_max_power_boundary_rule(model, t, s):
        return model.e[t, s] <= P_segments[segments][s + 1] * C_E * model.z_h[t, s]
    model.segment_max_power_boundary_constraint = Constraint(model.T, model.S, rule=segment_max_power_boundary_rule)

    # Hydrogen balance
    def hydrogen_balance_rule(model, t):
        return model.h[t] == model.h_d[t] + model.s_in[t]
    model.hydrogen_balance_constraint = Constraint(model.T, rule=hydrogen_balance_rule)

    # Demand balance
    def demand_balance_rule(model, t):
        return model.d[t] == model.h_d[t] + model.s_out[t]
    model.demand_balance_constraint = Constraint(model.T, rule=demand_balance_rule)

    # Maximum storage output
    def max_storage_output_rule(model, t):
        return model.s_out[t] <= C_E * eta_full_load
    model.max_storage_output_constraint = Constraint(model.T, rule=max_storage_output_rule)

    # Hydrogen min demand (DAILY)
    def min_hydrogen_demand_rule(model, tt):
        return sum(model.d[t] for t in TT[tt]) >= C_D
    model.min_hydrogen_demand_constraint = Constraint(Any, rule=min_hydrogen_demand_rule)

    # Maximum electrolyzer power
    def max_electrolyzer_power_rule(model, t):
        return model.e_tot[t] <= C_E * model.z_on[t] + P_sb * model.z_sb[t]
    model.max_electrolyzer_power_constraint = Constraint(model.T, rule=max_electrolyzer_power_rule)

    # Minimum electrolyzer power
    def min_electrolyzer_power_rule(model, t):
        return model.e_tot[t] >= P_min * model.z_on[t] + P_sb * model.z_sb[t]
    model.min_electrolyzer_power_constraint = Constraint(model.T, rule=min_electrolyzer_power_rule)

    # Only one efficiency if on or standby
    def one_efficiency_rule(model, t):
        return model.z_on[t] == sum(model.z_h[t, s] for s in model.S)
    model.one_efficiency_constraint = Constraint(model.T, rule=one_efficiency_rule)

    # States
    def states_constraint_rule(model, t):
        return 1 == model.z_on[t] + model.z_off[t] + model.z_sb[t]
    model.states_constraint = Constraint(model.T, rule=states_constraint_rule)

    # Not from Off to Standby
    def not_off_to_standby_rule(model, t):
        return 1 >= (model.z_sb[t] + model.z_off[t - 1]) if t > 1 else 0
    model.not_off_to_standby_constraint = Constraint(model.T, rule=not_off_to_standby_rule)

    # Startup cost
    def startup_cost_rule(model, t):
        return model.z_start[t] >= (model.z_on[t] - model.z_on[t - 1] - model.z_sb[t - 1]) if t > 1 else 0
    model.startup_cost_constraint = Constraint(model.T, rule=startup_cost_rule)

    # Compressor consumption
    def compressor_consumption_rule(model, t):
        return model.c[t] == model.s_in[t] * P_C
    model.compressor_consumption_constraint = Constraint(model.T, rule=compressor_consumption_rule)

    # Max storage fill
    def max_storage_fill_rule(model, t):
        return model.soc[t] <= C_S
    model.max_storage_fill_constraint = Constraint(model.T, rule=max_storage_fill_rule)

    # SOC
    def soc_rule(model, t):
        return model.soc[t] == (model.soc[t - 1] if t > 1 else 0) - model.s_out[t] + model.s_in[t]
    model.soc_constraint = Constraint(model.T, rule=soc_rule)

    #************************************************************************
    # Solve
    solver = SolverFactory('gurobi')
    solver.solve(model)

    # Report results
    print("-------------------------------------")
    if SolverStatus[model.SOLVER] == SolverStatus.ok and\
    TerminationCondition[model.SOLVER] == TerminationCondition.optimal:
        print(value(model.objective))
        output = pd.DataFrame()
        output['CF'] = CF
        output['Wind'] = P_W
        output['P'] = lambda_M
        output['H2_tresh'] = [lambda_M[t] / lambda_H for t in model.T]
        output['Sold_El'] = [value(model.m[t]) for t in model.T]
        output['Bought_El'] = [value(model.m_in[t]) for t in model.T]
        output['Elec'] = [value(model.e_tot[t]) for t in model.T]
        output['ON'] = [value(model.z_on[t]) for t in model.T]
        output['H2_prod'] = [value(model.h[t]) for t in model.T]
        eff_list = [value(model.h[t]) / sum(value(model.e[t, s]) for s in model.S) for t in model.T]
        output['Elec_Eff'] = eff_list
        output['Comp'] = [value(model.c[t]) for t in model.T]
        output['H2_store_in'] = [value(model.s_in[t]) for t in model.T]
        output['H2_store_out'] = [value(model.s_out[t]) for t in model.T]
        output['SOC'] = [value(model.soc[t]) for t in model.T]
        output['H2_sold'] = [value(model.d[t]) for t in model.T]
        print(output)
        print("\n\nRESULTS:")
        print(f"Objective value    = {round(value(model.objective), digits=digs)} EUR")
        print(f"Electricity        = {round(sum(value(model.m[t]) * lambda_M[t] for t in model.T), digits=digs)} EUR")
        print(f"Hydrogen           = {round(sum(value(model.d[t]) * lambda_H for t in model.T), digits=digs)} EUR")
        print(f"Max SOC            = {maximum([value(model.soc[t]) for t in model.T])}")
    else:
        print("No solution")
    print("\n--------------------------------------")


#************************************************************************
# Output to EXCEL
output.to_excel("m3s_ON_SB_$(segments)_segments.xlsx", index=False)

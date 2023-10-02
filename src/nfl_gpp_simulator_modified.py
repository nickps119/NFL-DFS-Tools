
import csv
import json
import math
import os
import random
import time
import numpy as np
import pulp as plp
import multiprocessing as mp
import pandas as pd
import statistics
import csv

import itertools
import collections
import re
from scipy.stats import norm, kendalltau, multivariate_normal, gamma
import matplotlib.pyplot as plt
import seaborn as sns
from collections import Counter, defaultdict
import math

class NFL_GPP_Simulator_Modified:
    config = None
    player_dict = {}
    pool_lineups = {}
    field_lineups = {}
    stacks_dict = {}
    gen_lineup_list = []
    roster_construction = []
    id_name_dict = {}
    salary = None
    optimal_score = None
    pool_size = None
    team_list = []
    num_iterations = None
    site = None
    payout_structure = {}
    use_contest_data = False
    entry_fee = None
    use_lineup_input = None
    matchups = set()
    projection_minimum = 15
    randomness_amount = 100
    min_lineup_salary = 48000
    max_pct_off_optimal = 0.4
    teams_dict = collections.defaultdict(list)  # Initialize teams_dict
    correlation_rules = {}
    def __init__(self, site, pool_size, field_size, num_fields, num_iterations, use_contest_data, use_file_upload, config_file='config.json'):
        # Loading the configuration from the config file
        with open(config_file, 'r') as file:
            self.config = json.load(file)
            
        self.pool_of_lineups = []  # This will store the pool of lineups
        self.num_of_lineups_in_pool = self.config.get('num_of_lineups_in_pool', 10)  # Default to 10 if not specified in config
        print(f"Number of lineups to be generated in the pool: {self.num_of_lineups_in_pool}")
        
        # Other initializations can remain the same as in the original class

    def __init__(
        self,
        site,
        pool_size,
        field_size,
        num_fields,
        num_iterations,
        use_contest_data,
        use_lineup_input,
    ):
        self.site = site
        self.use_lineup_input = use_lineup_input
        self.field_size = None
        self.pool_size = int(pool_size)
        self.load_config()
        self.load_rules()
        

        projection_path = os.path.join(
            os.path.dirname(__file__),
            "../{}_data/{}".format(site, self.config["projection_path"]),
        )
        self.load_projections(projection_path)

        player_path = os.path.join(
            os.path.dirname(__file__),
            "../{}_data/{}".format(site, self.config["player_path"]),
        )
        self.load_player_ids(player_path)
        self.load_team_stacks()

        # ownership_path = os.path.join(
        #    os.path.dirname(__file__),
        #    "../{}_data/{}".format(site, self.config["ownership_path"]),
        # )
        # self.load_ownership(ownership_path)

        # boom_bust_path = os.path.join(
        #    os.path.dirname(__file__),
        #    "../{}_data/{}".format(site, self.config["boom_bust_path"]),
        # )
        # self.load_boom_bust(boom_bust_path)

        #       batting_order_path = os.path.join(
        #           os.path.dirname(__file__),
        #            "../{}_data/{}".format(site, self.config["batting_order_path"]),
        #        )
        #        self.load_batting_order(batting_order_path)

        if site == "dk":
            self.roster_construction = [
                "QB",
                "RB",
                "RB",
                "WR",
                "WR",
                "WR",
                "TE",
                "FLEX",
                "DST",
            ]
            self.salary = 50000

        elif site == "fd":
            self.roster_construction = [
                "QB",
                "RB",
                "RB",
                "WR",
                "WR",
                "WR",
                "TE",
                "FLEX",
                "DST",
            ]
            self.salary = 60000

        self.use_contest_data = use_contest_data
        if use_contest_data:
            contest_path = os.path.join(
                os.path.dirname(__file__),
                "../{}_data/{}".format(site, self.config["contest_structure_path"]),
            )
            self.load_contest_data(contest_path)
            print("Contest payout structure loaded.")
        else:
            self.field_size = int(field_size)
            self.payout_structure = {0: 0.0}
            self.entry_fee = 0

        # self.adjust_default_stdev()
        self.assertPlayerDict()
        self.num_iterations = int(num_iterations)
        self.get_optimal()
        if self.use_lineup_input:
            self.load_lineups_from_file()
        # if self.match_lineup_input_to_pool_size or len(self.pool_lineups) == 0:
        # self.generate_pool_lineups()
        self.load_correlation_rules()

    # make column lookups on datafiles case insensitive
    def lower_first(self, iterator):
        return itertools.chain([next(iterator).lower()], iterator)

    def load_rules(self):
        self.projection_minimum = int(self.config["projection_minimum"])
        self.randomness_amount = float(self.config["randomness"])
        self.min_lineup_salary = int(self.config["min_lineup_salary"])
        self.max_pct_off_optimal = float(self.config["max_pct_off_optimal"])
        self.pct_field_using_stacks = float(self.config["pct_field_using_stacks"])
        self.default_qb_var = float(self.config["default_qb_var"])
        self.default_skillpos_var = float(self.config["default_skillpos_var"])
        self.default_def_var = float(self.config["default_def_var"])
        self.overlap_limit = float(self.config["num_players_vs_def"])
        self.pct_field_double_stacks = float(self.config["pct_field_double_stacks"])
        self.correlation_rules = self.config["custom_correlations"]

    def assertPlayerDict(self):
        for p, s in list(self.player_dict.items()):
            if s["ID"] == 0 or s["ID"] == "" or s["ID"] is None:
                print(
                    s["Name"]
                    + " name mismatch between projections and player ids, excluding from player_dict"
                )
                self.player_dict.pop(p)

    # In order to make reasonable tournament lineups, we want to be close enough to the optimal that
    # a person could realistically land on this lineup. Skeleton here is taken from base `mlb_optimizer.py`
    def get_optimal(self):
        # print(s['Name'],s['ID'])
        # print(self.player_dict)
        problem = plp.LpProblem("NFL", plp.LpMaximize)
        lp_variables = {
            self.player_dict[(player, pos_str, team)]["ID"]: plp.LpVariable(
                str(self.player_dict[(player, pos_str, team)]["ID"]), cat="Binary"
            )
            for (player, pos_str, team) in self.player_dict
        }

        # set the objective - maximize fpts
        problem += (
            plp.lpSum(
                self.player_dict[(player, pos_str, team)]["fieldFpts"]
                * lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                for (player, pos_str, team) in self.player_dict
            ),
            "Objective",
        )

        # Set the salary constraints
        problem += (
            plp.lpSum(
                self.player_dict[(player, pos_str, team)]["Salary"]
                * lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                for (player, pos_str, team) in self.player_dict
            )
            <= self.salary
        )

        if self.site == "dk":
            # Need 1 quarterback
            problem += (
                plp.lpSum(
                    lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                    for (player, pos_str, team) in self.player_dict
                    if "QB" in self.player_dict[(player, pos_str, team)]["Position"]
                )
                == 1
            )
            # Need at least 2 RBs can have up to 3 with FLEX slot
            problem += (
                plp.lpSum(
                    lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                    for (player, pos_str, team) in self.player_dict
                    if "RB" in self.player_dict[(player, pos_str, team)]["Position"]
                )
                >= 2
            )
            problem += (
                plp.lpSum(
                    lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                    for (player, pos_str, team) in self.player_dict
                    if "RB" in self.player_dict[(player, pos_str, team)]["Position"]
                )
                <= 3
            )
            # Need at least 3 WRs can have up to 4 with FLEX slot
            problem += (
                plp.lpSum(
                    lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                    for (player, pos_str, team) in self.player_dict
                    if "WR" in self.player_dict[(player, pos_str, team)]["Position"]
                )
                >= 3
            )
            problem += (
                plp.lpSum(
                    lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                    for (player, pos_str, team) in self.player_dict
                    if "WR" in self.player_dict[(player, pos_str, team)]["Position"]
                )
                <= 4
            )
            # Need at least 1 TE
            problem += (
                plp.lpSum(
                    lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                    for (player, pos_str, team) in self.player_dict
                    if "TE" in self.player_dict[(player, pos_str, team)]["Position"]
                )
                >= 1
            )
            problem += (
                plp.lpSum(
                    lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                    for (player, pos_str, team) in self.player_dict
                    if "TE" in self.player_dict[(player, pos_str, team)]["Position"]
                )
                <= 2
            )
            # Need 1 DEF
            problem += (
                plp.lpSum(
                    lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                    for (player, pos_str, team) in self.player_dict
                    if "DST" in self.player_dict[(player, pos_str, team)]["Position"]
                )
                == 1
            )
            # Can only roster 9 total players
            problem += (
                plp.lpSum(
                    lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                    for (player, pos_str, team) in self.player_dict
                )
                == 9
            )
            # Max 8 per team in case of weird issues with stacking on short slates
            for team in self.team_list:
                problem += (
                    plp.lpSum(
                        lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                        for (player, pos_str, team) in self.player_dict
                        if self.player_dict[(player, pos_str, team)]["Team"] == team
                    )
                    <= 8
                )

        elif self.site == "fd":
            # Need at least 1 point guard, can have up to 3 if utilizing G and UTIL slots
            problem += (
                plp.lpSum(
                    lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                    for (player, pos_str, team) in self.player_dict
                    if "QB" in self.player_dict[(player, pos_str, team)]["Position"]
                )
                == 1
            )
            # Need at least 2 RBs can have up to 3 with FLEX slot
            problem += (
                plp.lpSum(
                    lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                    for (player, pos_str, team) in self.player_dict
                    if "RB" in self.player_dict[(player, pos_str, team)]["Position"]
                )
                >= 2
            )
            problem += (
                plp.lpSum(
                    lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                    for (player, pos_str, team) in self.player_dict
                    if "RB" in self.player_dict[(player, pos_str, team)]["Position"]
                )
                <= 3
            )
            # Need at least 3 WRs can have up to 4 with FLEX slot
            problem += (
                plp.lpSum(
                    lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                    for (player, pos_str, team) in self.player_dict
                    if "WR" in self.player_dict[(player, pos_str, team)]["Position"]
                )
                >= 3
            )
            problem += (
                plp.lpSum(
                    lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                    for (player, pos_str, team) in self.player_dict
                    if "WR" in self.player_dict[(player, pos_str, team)]["Position"]
                )
                <= 4
            )
            # Need at least 1 TE
            problem += (
                plp.lpSum(
                    lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                    for (player, pos_str, team) in self.player_dict
                    if "TE" in self.player_dict[(player, pos_str, team)]["Position"]
                )
                >= 1
            )
            problem += (
                plp.lpSum(
                    lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                    for (player, pos_str, team) in self.player_dict
                    if "TE" in self.player_dict[(player, pos_str, team)]["Position"]
                )
                <= 2
            )
            # Need 1 DEF
            problem += (
                plp.lpSum(
                    lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                    for (player, pos_str, team) in self.player_dict
                    if "DST" in self.player_dict[(player, pos_str, team)]["Position"]
                )
                == 1
            )
            # Can only roster 9 total players
            problem += (
                plp.lpSum(
                    lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                    for (player, pos_str, team) in self.player_dict
                )
                == 9
            )
            # Max 4 per team
            for team in self.team_list:
                problem += (
                    plp.lpSum(
                        lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                        for (player, pos_str, team) in self.player_dict
                        if self.player_dict[(player, pos_str, team)]["Team"] == team
                    )
                    <= 4
                )

        # print(f"Problem Name: {problem.name}")
        # print(f"Sense: {problem.sense}")

        # # Print the objective
        # print("\nObjective:")
        # try:
        #     for v, coef in problem.objective.items():
        #         print(f"{coef}*{v.name}", end=' + ')
        # except Exception as e:
        #     print(f"Error while printing objective: {e}")

        # # Print the constraints
        # print("\nConstraints:")
        # for constraint in problem.constraints.values():
        #     try:
        #         # Extract the left-hand side, right-hand side, and the operator
        #         lhs = "".join(f"{coef}*{var.name}" for var, coef in constraint.items())
        #         rhs = constraint.constant
        #         if constraint.sense == 1:
        #             op = ">="
        #         elif constraint.sense == -1:
        #             op = "<="
        #         else:
        #             op = "="
        #         print(f"{lhs} {op} {rhs}")
        #     except Exception as e:
        #         print(f"Error while printing constraint: {e}")

        # # Print the variables
        # print("\nVariables:")
        # try:
        #     for v in problem.variables():
        #         print(f"{v.name}: LowBound={v.lowBound}, UpBound={v.upBound}, Cat={v.cat}")
        # except Exception as e:
        #     print(f"Error while printing variable: {e}")
        # Crunch!
        try:
            problem.solve(plp.PULP_CBC_CMD(msg=0))
        except plp.PulpSolverError:
            print(
                "Infeasibility reached - only generated {} lineups out of {}. Continuing with export.".format(
                    len(self.num_lineups), self.num_lineups
                )
            )
        except TypeError:
            for p, s in self.player_dict.items():
                if s["ID"] == 0:
                    print(
                        s["Name"] + " name mismatch between projections and player ids"
                    )
                if s["ID"] == "":
                    print(
                        s["Name"] + " name mismatch between projections and player ids"
                    )
                if s["ID"] is None:
                    print(s["Name"])
        score = str(problem.objective)
        for v in problem.variables():
            score = score.replace(v.name, str(v.varValue))

        self.optimal_score = eval(score)

    # Load player IDs for exporting
    def load_player_ids(self, path):
        with open(path, encoding="utf-8-sig") as file:
            reader = csv.DictReader(self.lower_first(file))
            for row in reader:
                name_key = "name" if self.site == "dk" else "nickname"
                player_name = row[name_key].replace("-", "#").lower().strip()
                # some players have 2 positions - will be listed like 'PG/SF' or 'PF/C'
                position = [pos for pos in row["position"].split("/")]
                position.sort()
                if self.site == "fd":
                    if "D" in position:
                        position = ["DST"]
                # if qb and dst not in position add flex
                if "QB" not in position and "DST" not in position:
                    position.append("FLEX")
                team_key = "teamabbrev" if self.site == "dk" else "team"
                team = row[team_key]
                game_info = "game info" if self.site == "dk" else "game"
                match = re.search(pattern="(\w{2,4}@\w{2,4})", string=row[game_info])
                if match:
                    opp = match.groups()[0].split("@")
                    self.matchups.add((opp[0], opp[1]))
                    for m in opp:
                        if m != team:
                            team_opp = m
                    opp = tuple(opp)
                # if not opp:
                #    print(row)
                pos_str = str(position)
                if (player_name, pos_str, team) in self.player_dict:
                    self.player_dict[(player_name, pos_str, team)]["ID"] = str(
                        row["id"]
                    )
                    self.player_dict[(player_name, pos_str, team)]["Team"] = row[
                        team_key
                    ]
                    self.player_dict[(player_name, pos_str, team)]["Opp"] = team_opp
                    self.player_dict[(player_name, pos_str, team)]["Matchup"] = opp
                self.id_name_dict[str(row["id"])] = row[name_key]

    def load_contest_data(self, path):
        with open(path, encoding="utf-8-sig") as file:
            reader = csv.DictReader(self.lower_first(file))
            for row in reader:
                if self.field_size is None:
                    self.field_size = int(row["field size"])
                if self.entry_fee is None:
                    self.entry_fee = float(row["entry fee"])
                # multi-position payouts
                if "-" in row["place"]:
                    indices = row["place"].split("-")
                    # print(indices)
                    # have to add 1 to range to get it to generate value for everything
                    for i in range(int(indices[0]), int(indices[1]) + 1):
                        # print(i)
                        # Where I'm from, we 0 index things. Thus, -1 since Payout starts at 1st place
                        if i >= self.field_size:
                            break
                        self.payout_structure[i - 1] = float(
                            row["payout"].split(".")[0].replace(",", "")
                        )
                # single-position payouts
                else:
                    if int(row["place"]) >= self.field_size:
                        break
                    self.payout_structure[int(row["place"]) - 1] = float(
                        row["payout"].split(".")[0].replace(",", "")
                    )
        # print(self.payout_structure)

    def load_correlation_rules(self):
        if len(self.correlation_rules.keys()) > 0:
            for c in self.correlation_rules.keys():
                for k in self.player_dict:
                    if (
                        c.replace("-", "#").lower().strip()
                        in self.player_dict[k].values()
                    ):
                        for v in self.correlation_rules[c].keys():
                            self.player_dict[k]["Correlations"][
                                v
                            ] = self.correlation_rules[c][v]

    # Load config from file
    def load_config(self):
        with open(
            os.path.join(os.path.dirname(__file__), "../config.json"),
            encoding="utf-8-sig",
        ) as json_file:
            self.config = json.load(json_file)

    # Load projections from file
    def load_projections(self, path):
        # Read projections into a dictionary
        with open(path, encoding="utf-8-sig") as file:
            reader = csv.DictReader(self.lower_first(file))
            for row in reader:
                player_name = row["name"].replace("-", "#").lower().strip()
                try:
                    fpts = float(row["fpts"])
                except:
                    fpts = 0
                    print(
                        "unable to load player fpts: "
                        + player_name
                        + ", fpts:"
                        + row["fpts"]
                    )
                if "fieldfpts" in row:
                    if row["fieldfpts"] == "":
                        fieldFpts = fpts
                    else:
                        fieldFpts = float(row["fieldfpts"])
                else:
                    fieldFpts = fpts
                position = [pos for pos in row["position"].split("/")]
                position.sort()
                # if qb and dst not in position add flex
                if self.site == "fd":
                    if "D" in position:
                        position = ["DST"]
                if "QB" not in position and "DST" not in position:
                    position.append("FLEX")
                pos = position[0]
                if "stddev" in row:
                    if row["stddev"] == "" or float(row["stddev"]) == 0:
                        if position == "QB":
                            stddev = fpts * self.default_qb_var
                        elif position == "DST":
                            stddev = fpts * self.default_def_var
                        else:
                            stddev = fpts * self.default_skillpos_var
                    else:
                        stddev = float(row["stddev"])
                else:
                    if position == "QB":
                        stddev = fpts * self.default_qb_var
                    elif position == "DST":
                        stddev = fpts * self.default_def_var
                    else:
                        stddev = fpts * self.default_skillpos_var
                # check if ceiling exists in row columns
                if "ceiling" in row:
                    if row["ceiling"] == "" or float(row["ceiling"]) == 0:
                        ceil = fpts + stddev
                    else:
                        ceil = float(row["ceiling"])
                else:
                    ceil = fpts + stddev
                if row["salary"]:
                    sal = int(row["salary"].replace(",", ""))
                if pos == "QB":
                    corr = {
                        "QB": 1,
                        "RB": 0.08,
                        "WR": 0.62,
                        "TE": 0.32,
                        "DST": -0.09,
                        "Opp QB": 0.24,
                        "Opp RB": 0.04,
                        "Opp WR": 0.19,
                        "Opp TE": 0.1,
                        "Opp DST": -0.41,
                    }
                elif pos == "RB":
                    corr = {
                        "QB": 0.08,
                        "RB": 1,
                        "WR": -0.09,
                        "TE": -0.02,
                        "DST": 0.07,
                        "Opp QB": 0.04,
                        "Opp RB": -0.08,
                        "Opp WR": 0.01,
                        "Opp TE": 0.03,
                        "Opp DST": -0.33,
                    }
                elif pos == "WR":
                    corr = {
                        "QB": 0.62,
                        "RB": -0.09,
                        "WR": 1,
                        "TE": -0.07,
                        "DST": -0.08,
                        "Opp QB": 0.19,
                        "Opp RB": 0.01,
                        "Opp WR": 0.16,
                        "Opp TE": 0.08,
                        "Opp DST": -0.22,
                    }
                elif pos == "TE":
                    corr = {
                        "QB": 0.32,
                        "RB": -0.02,
                        "WR": -0.07,
                        "TE": 1,
                        "DST": -0.08,
                        "Opp QB": 0.1,
                        "Opp RB": 0.03,
                        "Opp WR": 0.08,
                        "Opp TE": 0,
                        "Opp DST": -0.14,
                    }
                elif pos == "DST":
                    corr = {
                        "QB": -0.09,
                        "RB": 0.07,
                        "WR": -0.08,
                        "TE": -0.08,
                        "DST": 1,
                        "Opp QB": -0.41,
                        "Opp RB": -0.33,
                        "Opp WR": -0.22,
                        "Opp TE": -0.14,
                        "Opp DST": -0.27,
                    }
                team = row["team"]
                if team == "LA":
                    team = "LAR"
                if self.site == "fd":
                    if team == "JAX":
                        team = "JAC"
                own = float(row["own%"].replace("%", ""))
                if own == 0:
                    own = 0.1
                pos_str = str(position)
                player_data = {
                    "Fpts": fpts,
                    "fieldFpts": fieldFpts,
                    "Position": position,
                    "Name": player_name,
                    "Team": team,
                    "Opp": "",
                    "ID": "",
                    "Salary": int(row["salary"].replace(",", "")),
                    "StdDev": stddev,
                    "Ceiling": ceil,
                    "Ownership": own,
                    "Correlations": corr,
                    "In Lineup": False,
                }

                # Check if player is in player_dict and get Opp, ID, Opp Pitcher ID and Opp Pitcher Name
                if (player_name, pos_str, team) in self.player_dict:
                    player_data["Opp"] = self.player_dict[
                        (player_name, pos_str, team)
                    ].get("Opp", "")
                    player_data["ID"] = self.player_dict[
                        (player_name, pos_str, team)
                    ].get("ID", "")

                self.player_dict[(player_name, pos_str, team)] = player_data
                self.teams_dict[team].append(
                    player_data
                )  # Add player data to their respective team

    def load_team_stacks(self):
        # Initialize a dictionary to hold QB ownership by team
        qb_ownership_by_team = {}

        for p in self.player_dict:
            # Check if player is a QB
            if "QB" in self.player_dict[p]["Position"]:
                # Fetch the team of the QB
                team = self.player_dict[p]["Team"]

                # Convert the ownership percentage string to a float and divide by 100
                own_percentage = float(self.player_dict[p]["Ownership"]) / 100

                # Add the ownership to the accumulated ownership for the team
                if team in qb_ownership_by_team:
                    qb_ownership_by_team[team] += own_percentage
                else:
                    qb_ownership_by_team[team] = own_percentage

        # Now, update the stacks_dict with the QB ownership by team
        for team, own_percentage in qb_ownership_by_team.items():
            self.stacks_dict[team] = own_percentage

    def extract_id(self, cell_value):
        if "(" in cell_value and ")" in cell_value:
            return cell_value.split("(")[1].replace(")", "")
        else:
            return cell_value

    def load_lineups_from_file(self):
        print("loading lineups")
        i = 0
        path = os.path.join(
            os.path.dirname(__file__),
            "../{}_data/{}".format(self.site, "tournament_lineups.csv"),
        )
        with open(path) as file:
            reader = pd.read_csv(file)
            lineup = []
            j = 0
            for i, row in reader.iterrows():
                # print(row)
                if i == self.pool_size:
                    break
                lineup = [self.extract_id(str(row[j])) for j in range(9)]
                # storing if this lineup was made by an optimizer or with the generation process in this script
                error = False
                for l in lineup:
                    ids = [self.player_dict[k]["ID"] for k in self.player_dict]
                    if l not in ids:
                        print("lineup {} is missing players {}".format(i, l))
                        if l in self.id_name_dict:
                            print(self.id_name_dict[l])
                        error = True
                if len(lineup) < 9:
                    print("lineup {} is missing players".format(i))
                    continue
                # storing if this lineup was made by an optimizer or with the generation process in this script
                error = False
                for l in lineup:
                    ids = [self.player_dict[k]["ID"] for k in self.player_dict]
                    if l not in ids:
                        print("lineup {} is missing players {}".format(i, l))
                        if l in self.id_name_dict:
                            print(self.id_name_dict[l])
                        error = True
                if len(lineup) < 9:
                    print("lineup {} is missing players".format(i))
                    continue
                if not error:
                    # reshuffle lineup to match temp_roster_construction
                    temp_roster_construction = [
                        "DST",
                        "QB",
                        "RB",
                        "RB",
                        "WR",
                        "WR",
                        "WR",
                        "TE",
                        "FLEX",
                    ]
                    shuffled_lu = []

                    id_to_player_dict = {
                        v["ID"]: v for k, v in self.player_dict.items()
                    }
                    lineup_copy = lineup.copy()
                    position_counts = {
                        "DST": 0,
                        "QB": 0,
                        "RB": 0,
                        "WR": 0,
                        "TE": 0,
                        "FLEX": 0,
                    }
                    z = 0

                    while z < 9:
                        for t in temp_roster_construction:
                            if position_counts[t] < temp_roster_construction.count(t):
                                for l in lineup_copy:
                                    player_info = id_to_player_dict.get(l)
                                    if player_info and t in player_info["Position"]:
                                        shuffled_lu.append(l)
                                        lineup_copy.remove(l)
                                        position_counts[t] += 1
                                        z += 1
                                        if z == 9:
                                            break
                            if z == 9:
                                break
                    self.pool_lineups[j] = {
                        "Lineup": shuffled_lu,
                    }
                    j += 1
        print("loaded {} lineups".format(j))
        # print(self.pool_lineups)

    @staticmethod
    def generate_lineups(
        lu_num,
        ids,
        in_lineup,
        pos_matrix,
        ownership,
        salary_floor,
        salary_ceiling,
        optimal_score,
        salaries,
        projections,
        max_pct_off_optimal,
        teams,
        opponents,
        team_stack,
        stack_len,
        overlap_limit,
        max_stack_len,
        matchups,
        num_players_in_roster,
        site,
    ):
        # new random seed for each lineup (without this there is a ton of dupes)
        rng = np.random.default_rng()
        lus = {}
        # make sure nobody is already showing up in a lineup
        if sum(in_lineup) != 0:
            in_lineup.fill(0)
        reject = True
        iteration_count = 0
        total_players = num_players_in_roster
        issue = ""
        complete = ""
        reasonable_projection = optimal_score - (max_pct_off_optimal * optimal_score)
        reasonable_stack_projection = optimal_score - (
            (max_pct_off_optimal * 1.25) * optimal_score
        )
        max_players_per_team = 4 if site == "fd" else None
        # reject_counters = {
        #     "salary_too_low": 0,
        #     "salary_too_high": 0,
        #     "projection_too_low": 0,
        #     "invalid_matchups": 0,
        #     "stack_length_insufficient": 0,
        # }
        # print(lu_num, ' started',  team_stack, max_stack_len)
        while reject:
            iteration_count += 1
            if team_stack == "":
                salary = 0
                proj = 0
                if sum(in_lineup) != 0:
                    in_lineup.fill(0)
                lineup = []
                player_teams = []
                def_opps = []
                players_opposing_def = 0
                lineup_matchups = []
                k = 0
                for pos in pos_matrix.T:
                    if k < 1:
                        # check for players eligible for the position and make sure they arent in a lineup, returns a list of indices of available player
                        valid_players = np.nonzero((pos > 0) & (in_lineup == 0))[0]
                        # grab names of players eligible
                        plyr_list = ids[valid_players]
                        # create np array of probability of being seelcted based on ownership and who is eligible at the position
                        prob_list = ownership[valid_players]
                        prob_list = prob_list / prob_list.sum()
                        try:
                            choice = rng.choice(plyr_list, p=prob_list)
                        except:
                            print(plyr_list, prob_list)
                        choice_idx = np.nonzero(ids == choice)[0]
                        lineup.append(str(choice))
                        in_lineup[choice_idx] = 1
                        salary += salaries[choice_idx]
                        proj += projections[choice_idx]
                        def_opp = opponents[choice_idx][0]
                        lineup_matchups.append(matchups[choice_idx[0]])
                        player_teams.append(teams[choice_idx][0])
                    if k >= 1:
                        remaining_salary = salary_ceiling - salary
                        if players_opposing_def < overlap_limit:
                            if k == total_players - 1:
                                valid_players = np.nonzero(
                                    (pos > 0)
                                    & (in_lineup == 0)
                                    & (salaries <= remaining_salary)
                                    & (salary + salaries >= salary_floor)
                                )[0]
                            else:
                                valid_players = np.nonzero(
                                    (pos > 0)
                                    & (in_lineup == 0)
                                    & (salaries <= remaining_salary)
                                )[0]
                            # grab names of players eligible
                            plyr_list = ids[valid_players]
                            # create np array of probability of being seelcted based on ownership and who is eligible at the position
                            prob_list = ownership[valid_players]
                            prob_list = prob_list / prob_list.sum()
                            try:
                                choice = rng.choice(plyr_list, p=prob_list)
                            except:
                                # if remaining_salary <= np.min(salaries):
                                #     reject_counters["salary_too_high"] += 1
                                # else:
                                #     reject_counters["salary_too_low"]
                                salary = 0
                                proj = 0
                                if team_stack == "":
                                    lineup = []
                                else:
                                    lineup = np.zeros(shape=pos_matrix.shape[1]).astype(
                                        str
                                    )
                                player_teams = []
                                def_opps = []
                                players_opposing_def = 0
                                lineup_matchups = []
                                in_lineup.fill(0)  # Reset the in_lineup array
                                k = 0  # Reset the player index
                                continue  # Skip to the next iteration of the while loop
                            choice_idx = np.nonzero(ids == choice)[0]
                            lineup.append(str(choice))
                            in_lineup[choice_idx] = 1
                            salary += salaries[choice_idx]
                            proj += projections[choice_idx]
                            player_teams.append(teams[choice_idx][0])
                            lineup_matchups.append(matchups[choice_idx[0]])
                            if teams[choice_idx][0] == def_opp:
                                players_opposing_def += 1
                            if max_players_per_team is not None:
                                team_count = Counter(player_teams)
                                if any(
                                    count > max_players_per_team
                                    for count in team_count.values()
                                ):
                                    salary = 0
                                    proj = 0
                                    if team_stack == "":
                                        lineup = []
                                    else:
                                        lineup = np.zeros(
                                            shape=pos_matrix.shape[1]
                                        ).astype(str)
                                    player_teams = []
                                    def_opps = []
                                    players_opposing_def = 0
                                    lineup_matchups = []
                                    in_lineup.fill(0)  # Reset the in_lineup array
                                    k = 0  # Reset the player index
                                    continue  # Skip to the next iteration of the while loop
                        else:
                            if k == total_players - 1:
                                valid_players = np.nonzero(
                                    (pos > 0)
                                    & (in_lineup == 0)
                                    & (salaries <= remaining_salary)
                                    & (salary + salaries >= salary_floor)
                                )[0]
                            else:
                                valid_players = np.nonzero(
                                    (pos > 0)
                                    & (in_lineup == 0)
                                    & (salaries <= remaining_salary)
                                )[0]
                            # grab names of players eligible
                            plyr_list = ids[valid_players]
                            # create np array of probability of being seelcted based on ownership and who is eligible at the position
                            prob_list = ownership[valid_players]
                            prob_list = prob_list / prob_list.sum()
                            try:
                                choice = rng.choice(plyr_list, p=prob_list)
                            except:
                                salary = 0
                                proj = 0
                                if team_stack == "":
                                    lineup = []
                                else:
                                    lineup = np.zeros(shape=pos_matrix.shape[1]).astype(
                                        str
                                    )
                                player_teams = []
                                def_opps = []
                                players_opposing_def = 0
                                lineup_matchups = []
                                in_lineup.fill(0)  # Reset the in_lineup array
                                k = 0  # Reset the player index
                                continue  # Skip to the next iteration of the while loop
                                # if remaining_salary <= np.min(salaries):
                                #     reject_counters["salary_too_high"] += 1
                                # else:
                                #     reject_counters["salary_too_low"]
                            choice_idx = np.nonzero(ids == choice)[0]
                            lineup.append(str(choice))
                            in_lineup[choice_idx] = 1
                            salary += salaries[choice_idx]
                            proj += projections[choice_idx]
                            player_teams.append(teams[choice_idx][0])
                            lineup_matchups.append(matchups[choice_idx[0]])
                            if teams[choice_idx][0] == def_opp:
                                players_opposing_def += 1
                            if max_players_per_team is not None:
                                team_count = Counter(player_teams)
                                if any(
                                    count > max_players_per_team
                                    for count in team_count.values()
                                ):
                                    salary = 0
                                    proj = 0
                                    if team_stack == "":
                                        lineup = []
                                    else:
                                        lineup = np.zeros(
                                            shape=pos_matrix.shape[1]
                                        ).astype(str)
                                    player_teams = []
                                    def_opps = []
                                    players_opposing_def = 0
                                    lineup_matchups = []
                                    in_lineup.fill(0)  # Reset the in_lineup array
                                    k = 0  # Reset the player index
                                    continue  # Skip to the next iteration of the while loop
                    k += 1
                # Must have a reasonable salary
                # if salary > salary_ceiling:
                #     reject_counters["salary_too_high"] += 1
                # elif salary < salary_floor:
                #     reject_counters["salary_too_low"] += 1
                if salary >= salary_floor and salary <= salary_ceiling:
                    # Must have a reasonable projection (within 60% of optimal) **people make a lot of bad lineups
                    if proj >= reasonable_projection:
                        if len(set(lineup_matchups)) > 1:
                            if max_players_per_team is not None:
                                team_count = Counter(player_teams)
                                if all(
                                    count <= max_players_per_team
                                    for count in team_count.values()
                                ):
                                    reject = False
                                    lus[lu_num] = {
                                        "Lineup": lineup,
                                        }
                                    if len(set(lineup)) != 9:
                                        print(
                                            "non stack lineup dupes",
                                            lu_num,
                                            plyr_stack_indices,
                                            str(lu_num),
                                            salaries[plyr_stack_indices],
                                            lineup,
                                            stack_len,
                                            team_stack,
                                            x,
                                        )
                            else:
                                reject = False
                                lus[lu_num] = {
                                    "Lineup": lineup,
                                    }
                                if len(set(lineup)) != 9:
                                    print(
                                        "stack lineup dupes",
                                        lu_num,
                                        plyr_stack_indices,
                                        str(lu_num),
                                        salaries[plyr_stack_indices],
                                        lineup,
                                        stack_len,
                                        team_stack,
                                        x,
                                    )
                            # complete = 'completed'
                            # print(str(lu_num) + ' ' + complete)
                    #     else:
                    #         reject_counters["invalid_matchups"] += 1
                    # else:
                    #     reject_counters["projection_too_low"] += 1
            else:
                salary = 0
                proj = 0
                if sum(in_lineup) != 0:
                    in_lineup.fill(0)
                player_teams = []
                def_opps = []
                lineup_matchups = []
                filled_pos = np.zeros(shape=pos_matrix.shape[1])
                team_stack_len = 0
                k = 0
                stack = True
                lineup = np.zeros(shape=pos_matrix.shape[1]).astype(str)
                valid_team = np.nonzero(teams == team_stack)[0]
                # select qb
                qb = np.unique(
                    valid_team[np.nonzero(pos_matrix[valid_team, 1] > 0)[0]]
                )[0]
                salary += salaries[qb]
                proj += projections[qb]
                # print(salary)
                team_stack_len += 1
                lineup[1] = ids[qb]
                in_lineup[qb] = 1
                lineup_matchups.append(matchups[qb])
                valid_players = np.unique(
                    valid_team[np.nonzero(pos_matrix[valid_team, 4:8] > 0)[0]]
                )
                player_teams.append(teams[qb])
                players_opposing_def = 0
                plyr_list = ids[valid_players]
                prob_list = ownership[valid_players]
                prob_list = prob_list / prob_list.sum()
                while stack:
                    try:
                        choices = rng.choice(
                            a=plyr_list, p=prob_list, size=stack_len, replace=False
                        )
                        if len(set(choices)) != len(choices):
                            print(
                                "choice dupe",
                                plyr_stack_indices,
                                str(lu_num),
                                salaries[plyr_stack_indices],
                                lineup,
                                stack_len,
                                team_stack,
                                x,
                            )
                    except:
                        stack = False
                        continue
                    plyr_stack_indices = np.nonzero(np.in1d(ids, choices))[0]
                    x = 0
                    for p in plyr_stack_indices:
                        player_placed = False
                        for l in np.nonzero(pos_matrix[p] > 0)[0]:
                            if lineup[l] == "0.0":
                                lineup[l] = ids[p]
                                lineup_matchups.append(matchups[p])
                                player_teams.append(teams[p])
                                x += 1
                                player_placed = True
                                break
                            if player_placed:
                                break
                    # print(plyr_stack_indices, str(lu_num), salaries[plyr_stack_indices], lineup, stack_len, x)
                    if x == stack_len:
                        in_lineup[plyr_stack_indices] = 1
                        salary += sum(salaries[plyr_stack_indices])
                        # rint(salary)
                        proj += sum(projections[plyr_stack_indices])
                        # print(proj)
                        team_stack_len += stack_len
                        x = 0
                        stack = False
                    else:
                        stack = False
                # print(sum(in_lineup), stack_len)
                for ix, (l, pos) in enumerate(zip(lineup, pos_matrix.T)):
                    if l == "0.0":
                        if k < 1:
                            valid_players = np.nonzero(
                                (pos > 0) & (in_lineup == 0) & (opponents != team_stack)
                            )[0]
                            # grab names of players eligible
                            plyr_list = ids[valid_players]
                            # create np array of probability of being selected based on ownership and who is eligible at the position
                            prob_list = ownership[valid_players]
                            prob_list = prob_list / prob_list.sum()
                            # try:
                            choice = rng.choice(plyr_list, p=prob_list)
                            # except:
                            #    print(k, pos)
                            choice_idx = np.nonzero(ids == choice)[0]
                            in_lineup[choice_idx] = 1
                            try:
                                lineup[ix] = str(choice)
                            except IndexError:
                                print(lineup, choice, ix)
                            salary += salaries[choice_idx]
                            proj += projections[choice_idx]
                            def_opp = opponents[choice_idx][0]
                            lineup_matchups.append(matchups[choice_idx[0]])
                            k += 1
                        elif k >= 1:
                            remaining_salary = salary_ceiling - salary
                            if players_opposing_def < overlap_limit:
                                if k == total_players - 1:
                                    valid_players = np.nonzero(
                                        (pos > 0)
                                        & (in_lineup == 0)
                                        & (salaries <= remaining_salary)
                                        & (salary + salaries >= salary_floor)
                                    )[0]
                                else:
                                    valid_players = np.nonzero(
                                        (pos > 0)
                                        & (in_lineup == 0)
                                        & (salaries <= remaining_salary)
                                    )[0]
                                # grab names of players eligible
                                plyr_list = ids[valid_players]
                                # create np array of probability of being seelcted based on ownership and who is eligible at the position
                                prob_list = ownership[valid_players]
                                prob_list = prob_list / prob_list.sum()
                                try:
                                    choice = rng.choice(plyr_list, p=prob_list)
                                except:
                                    salary = 0
                                    proj = 0
                                    if team_stack == "":
                                        lineup = []
                                    else:
                                        lineup = np.zeros(
                                            shape=pos_matrix.shape[1]
                                        ).astype(str)
                                    player_teams = []
                                    def_opps = []
                                    players_opposing_def = 0
                                    lineup_matchups = []
                                    in_lineup.fill(0)  # Reset the in_lineup array
                                    k = 0  # Reset the player index
                                    continue  # Skip to the next iteration of the while loop
                                    # if remaining_salary <= np.min(salaries):
                                    #     reject_counters["salary_too_high"] += 1
                                    # else:
                                    #     reject_counters["salary_too_low"]
                                choice_idx = np.nonzero(ids == choice)[0]
                                try:
                                    lineup[ix] = str(choice)
                                except IndexError:
                                    print(lineup, choice, ix)
                                in_lineup[choice_idx] = 1
                                salary += salaries[choice_idx]
                                proj += projections[choice_idx]
                                player_teams.append(teams[choice_idx][0])
                                lineup_matchups.append(matchups[choice_idx[0]])
                                if max_players_per_team is not None:
                                    team_count = Counter(player_teams)
                                    if any(
                                        count > max_players_per_team
                                        for count in team_count.values()
                                    ):
                                        salary = 0
                                        proj = 0
                                        if team_stack == "":
                                            lineup = []
                                        else:
                                            lineup = np.zeros(
                                                shape=pos_matrix.shape[1]
                                            ).astype(str)
                                        player_teams = []
                                        def_opps = []
                                        players_opposing_def = 0
                                        lineup_matchups = []
                                        in_lineup.fill(0)  # Reset the in_lineup array
                                        k = 0  # Reset the player index
                                        continue  # Skip to the next iteration of the while loop
                                if teams[choice_idx][0] == def_opp:
                                    players_opposing_def += 1
                                if teams[choice_idx][0] == team_stack:
                                    team_stack_len += 1
                            else:
                                if k == total_players - 1:
                                    valid_players = np.nonzero(
                                        (pos > 0)
                                        & (in_lineup == 0)
                                        & (salaries <= remaining_salary)
                                        & (salary + salaries >= salary_floor)
                                    )[0]
                                else:
                                    valid_players = np.nonzero(
                                        (pos > 0)
                                        & (in_lineup == 0)
                                        & (salaries <= remaining_salary)
                                    )[0]
                                # grab names of players eligible
                                plyr_list = ids[valid_players]
                                # create np array of probability of being seelcted based on ownership and who is eligible at the position
                                prob_list = ownership[valid_players]
                                prob_list = prob_list / prob_list.sum()
                                try:
                                    choice = rng.choice(plyr_list, p=prob_list)
                                except:
                                    salary = 0
                                    proj = 0
                                    if team_stack == "":
                                        lineup = []
                                    else:
                                        lineup = np.zeros(
                                            shape=pos_matrix.shape[1]
                                        ).astype(str)
                                    player_teams = []
                                    def_opps = []
                                    players_opposing_def = 0
                                    lineup_matchups = []
                                    in_lineup.fill(0)  # Reset the in_lineup array
                                    k = 0  # Reset the player index
                                    continue  # Skip to the next iteration of the while loop
                                    # if remaining_salary <= np.min(salaries):
                                    #     reject_counters["salary_too_high"] += 1
                                    # else:
                                    #     reject_counters["salary_too_low"]
                                choice_idx = np.nonzero(ids == choice)[0]
                                lineup[ix] = str(choice)
                                in_lineup[choice_idx] = 1
                                salary += salaries[choice_idx]
                                proj += projections[choice_idx]
                                player_teams.append(teams[choice_idx][0])
                                lineup_matchups.append(matchups[choice_idx[0]])
                                if teams[choice_idx][0] == def_opp:
                                    players_opposing_def += 1
                                if teams[choice_idx][0] == team_stack:
                                    team_stack_len += 1
                                if max_players_per_team is not None:
                                    team_count = Counter(player_teams)
                                    if any(
                                        count > max_players_per_team
                                        for count in team_count.values()
                                    ):
                                        salary = 0
                                        proj = 0
                                        if team_stack == "":
                                            lineup = []
                                        else:
                                            lineup = np.zeros(
                                                shape=pos_matrix.shape[1]
                                            ).astype(str)
                                        player_teams = []
                                        def_opps = []
                                        players_opposing_def = 0
                                        lineup_matchups = []
                                        in_lineup.fill(0)  # Reset the in_lineup array
                                        k = 0  # Reset the player index
                                        continue  # Skip to the next iteration of the while loop
                            k += 1
                    else:
                        k += 1
                # Must have a reasonable salary
                if team_stack_len >= stack_len:
                    if salary >= salary_floor and salary <= salary_ceiling:
                        # loosening reasonable projection constraint for team stacks
                        if proj >= reasonable_stack_projection:
                            if len(set(lineup_matchups)) > 1:
                                if max_players_per_team is not None:
                                    team_count = Counter(player_teams)
                                    if all(
                                        count <= max_players_per_team
                                        for count in team_count.values()
                                    ):
                                        reject = False
                                        lus[lu_num] = {
                                            "Lineup": lineup,
                                        }
                                        if len(set(lineup)) != 9:
                                            print(
                                                "stack lineup dupes",
                                                lu_num,
                                                plyr_stack_indices,
                                                str(lu_num),
                                                salaries[plyr_stack_indices],
                                                lineup,
                                                stack_len,
                                                team_stack,
                                                x,
                                            )

                                else:
                                    reject = False
                                    lus[lu_num] = {
                                        "Lineup": lineup,
                                    }
                                    if len(set(lineup)) != 9:
                                        print(
                                            "stack lineup dupes",
                                            lu_num,
                                            plyr_stack_indices,
                                            str(lu_num),
                                            salaries[plyr_stack_indices],
                                            lineup,
                                            stack_len,
                                            team_stack,
                                            x,
                                        )
                #             else:
                #                 reject_counters["invalid_matchups"] += 1
                #         else:
                #             reject_counters["projection_too_low"] += 1
                #     else:
                #         if salary > salary_ceiling:
                #             reject_counters["salary_too_high"] += 1
                #         elif salary < salary_floor:
                #             reject_counters["salary_too_low"] += 1
                # else:
                #     reject_counters["stack_length_insufficient"] += 1
        # return lus, reject_counters
        return lus

    def generate_pool_lineups(self):
        diff = self.pool_size - len(self.pool_lineups)
        if diff <= 0:
            print(
                "supplied lineups >= contest pool size. only retrieving the first "
                + str(self.pool_size)
                + " lineups"
            )
        else:
            print("Generating " + str(diff) + " lineups.")
            ids = []
            ownership = []
            salaries = []
            projections = []
            positions = []
            teams = []
            opponents = []
            matchups = []
            # put def first to make it easier to avoid overlap
            temp_roster_construction = [
                "DST",
                "QB",
                "RB",
                "RB",
                "WR",
                "WR",
                "WR",
                "TE",
                "FLEX",
            ]
            for k in self.player_dict.keys():
                if "Team" not in self.player_dict[k].keys():
                    print(
                        self.player_dict[k]["Name"],
                        " name mismatch between projections and player ids!",
                    )
                ids.append(self.player_dict[k]["ID"])
                ownership.append(self.player_dict[k]["Ownership"])
                salaries.append(self.player_dict[k]["Salary"])
                if self.player_dict[k]["fieldFpts"] >= self.projection_minimum:
                    projections.append(self.player_dict[k]["fieldFpts"])
                else:
                    projections.append(0)
                teams.append(self.player_dict[k]["Team"])
                opponents.append(self.player_dict[k]["Opp"])
                matchups.append(self.player_dict[k]["Matchup"])
                pos_list = []
                for pos in temp_roster_construction:
                    if pos in self.player_dict[k]["Position"]:
                        pos_list.append(1)
                    else:
                        pos_list.append(0)
                positions.append(np.array(pos_list))
            in_lineup = np.zeros(shape=len(ids))
            ownership = np.array(ownership)
            salaries = np.array(salaries)
            projections = np.array(projections)
            pos_matrix = np.array(positions)
            ids = np.array(ids)
            optimal_score = self.optimal_score
            salary_floor = self.min_lineup_salary
            salary_ceiling = self.salary
            max_pct_off_optimal = self.max_pct_off_optimal
            stack_usage = self.pct_field_using_stacks
            teams = np.array(teams)
            opponents = np.array(opponents)
            overlap_limit = self.overlap_limit
            problems = []
            stacks = np.random.binomial(n=1, p=self.pct_field_using_stacks, size=diff)
            stack_len = np.random.choice(
                a=[1, 2],
                p=[1 - self.pct_field_double_stacks, self.pct_field_double_stacks],
                size=diff,
            )
            max_stack_len = 2
            num_players_in_roster = len(self.roster_construction)
            a = list(self.stacks_dict.keys())
            p = np.array(list(self.stacks_dict.values()))
            probs = p / sum(p)
            stacks = stacks.astype(str)
            for i in range(len(stacks)):
                if stacks[i] == "1":
                    choice = random.choices(a, weights=probs, k=1)
                    stacks[i] = choice[0]
                else:
                    stacks[i] = ""
            # creating tuples of the above np arrays plus which lineup number we are going to create
            for i in range(diff):
                lu_tuple = (
                    i,
                    ids,
                    in_lineup,
                    pos_matrix,
                    ownership,
                    salary_floor,
                    salary_ceiling,
                    optimal_score,
                    salaries,
                    projections,
                    max_pct_off_optimal,
                    teams,
                    opponents,
                    stacks[i],
                    stack_len[i],
                    overlap_limit,
                    max_stack_len,
                    matchups,
                    num_players_in_roster,
                    self.site,
                )
                problems.append(lu_tuple)
            start_time = time.time()
            with mp.Pool() as pool:
                output = pool.starmap(self.generate_lineups, problems)
                print(
                    "number of running processes =",
                    pool.__dict__["_processes"]
                    if (pool.__dict__["_state"]).upper() == "RUN"
                    else None,
                )
                pool.close()
                pool.join()
            print("pool closed")
            if len(self.pool_lineups) == 0:
                new_keys = list(range(0, self.pool_size))
            else:
                new_keys = list(
                    range(max(self.pool_lineups.keys()) + 1, self.pool_size)
                )
            nk = new_keys[0]
            # overall_reject_counters = defaultdict(int)
            # for i, (lineup, reject_counter) in enumerate(output):
            #     if nk in self.pool_lineups.keys():
            #         print("bad lineups dict, please check dk_data files")

            #     # Merge the reject counters into the overall counter
            #     for key, value in reject_counter.items():
            #         overall_reject_counters[key] += value

            #     self.pool_lineups[nk] = lineup  # Adjusted to handle the unpacked tuple
            #     nk += 1
            for i, o in enumerate(output):
                if nk in self.pool_lineups.keys():
                    print("bad lineups dict, please check dk_data files")
                self.pool_lineups[nk] = o[i]
                nk += 1
            end_time = time.time()
            print("lineups took " + str(end_time - start_time) + " seconds")
            print(str(diff) + " pool lineups successfully generated")
# Printing the generated lineups to ensure they are being generated properly
            print("Generated pool Lineups: ", self.pool_lineups)
            # print("Reject counters:", dict(overall_reject_counters))

            # print(self.pool_lineups)
            return(self.pool_lineups)

    def generate_field_lineups(self):
        diff = self.field_size - len(self.field_lineups)
        if diff <= 0:
            print(
                "supplied lineups >= contest field size. only retrieving the first "
                + str(self.field_size)
                + " lineups"
            )
        else:
            print("Generating " + str(diff) + " lineups.")
            ids = []
            ownership = []
            salaries = []
            projections = []
            positions = []
            teams = []
            opponents = []
            matchups = []
            # put def first to make it easier to avoid overlap
            temp_roster_construction = [
                "DST",
                "QB",
                "RB",
                "RB",
                "WR",
                "WR",
                "WR",
                "TE",
                "FLEX",
            ]
            for k in self.player_dict.keys():
                if "Team" not in self.player_dict[k].keys():
                    print(
                        self.player_dict[k]["Name"],
                        " name mismatch between projections and player ids!",
                    )
                ids.append(self.player_dict[k]["ID"])
                ownership.append(self.player_dict[k]["Ownership"])
                salaries.append(self.player_dict[k]["Salary"])
                if self.player_dict[k]["fieldFpts"] >= self.projection_minimum:
                    projections.append(self.player_dict[k]["fieldFpts"])
                else:
                    projections.append(0)
                teams.append(self.player_dict[k]["Team"])
                opponents.append(self.player_dict[k]["Opp"])
                matchups.append(self.player_dict[k]["Matchup"])
                pos_list = []
                for pos in temp_roster_construction:
                    if pos in self.player_dict[k]["Position"]:
                        pos_list.append(1)
                    else:
                        pos_list.append(0)
                positions.append(np.array(pos_list))
            in_lineup = np.zeros(shape=len(ids))
            ownership = np.array(ownership)
            salaries = np.array(salaries)
            projections = np.array(projections)
            pos_matrix = np.array(positions)
            ids = np.array(ids)
            optimal_score = self.optimal_score
            salary_floor = self.min_lineup_salary
            salary_ceiling = self.salary
            max_pct_off_optimal = self.max_pct_off_optimal
            stack_usage = self.pct_field_using_stacks
            teams = np.array(teams)
            opponents = np.array(opponents)
            overlap_limit = self.overlap_limit
            problems = []
            stacks = np.random.binomial(n=1, p=self.pct_field_using_stacks, size=diff)
            stack_len = np.random.choice(
                a=[1, 2],
                p=[1 - self.pct_field_double_stacks, self.pct_field_double_stacks],
                size=diff,
            )
            max_stack_len = 2
            num_players_in_roster = len(self.roster_construction)
            a = list(self.stacks_dict.keys())
            p = np.array(list(self.stacks_dict.values()))
            probs = p / sum(p)
            stacks = stacks.astype(str)
            for i in range(len(stacks)):
                if stacks[i] == "1":
                    choice = random.choices(a, weights=probs, k=1)
                    stacks[i] = choice[0]
                else:
                    stacks[i] = ""
            # creating tuples of the above np arrays plus which lineup number we are going to create
            for i in range(diff):
                lu_tuple = (
                    i,
                    ids,
                    in_lineup,
                    pos_matrix,
                    ownership,
                    salary_floor,
                    salary_ceiling,
                    optimal_score,
                    salaries,
                    projections,
                    max_pct_off_optimal,
                    teams,
                    opponents,
                    stacks[i],
                    stack_len[i],
                    overlap_limit,
                    max_stack_len,
                    matchups,
                    num_players_in_roster,
                    self.site,
                )
                problems.append(lu_tuple)
            start_time = time.time()
            with mp.Pool() as pool:
                output = pool.starmap(self.generate_lineups, problems)
                print(
                    "number of running processes =",
                    pool.__dict__["_processes"]
                    if (pool.__dict__["_state"]).upper() == "RUN"
                    else None,
                )
                pool.close()
                pool.join()
            print("pool closed")
            if len(self.field_lineups) == 0:
                new_keys = list(range(0, self.field_size))
            else:
                new_keys = list(
                    range(max(self.field_lineups.keys()) + 1, self.field_size)
                )
            nk = new_keys[0]
            # overall_reject_counters = defaultdict(int)
            # for i, (lineup, reject_counter) in enumerate(output):
            #     if nk in self.field_lineups.keys():
            #         print("bad lineups dict, please check dk_data files")

            #     # Merge the reject counters into the overall counter
            #     for key, value in reject_counter.items():
            #         overall_reject_counters[key] += value

            #     self.field_lineups[nk] = lineup  # Adjusted to handle the unpacked tuple
            #     nk += 1
            for i, o in enumerate(output):
                if nk in self.field_lineups.keys():
                    print("bad lineups dict, please check dk_data files")
                self.field_lineups[nk] = o[i]
                nk += 1
            end_time = time.time()
            print("lineups took " + str(end_time - start_time) + " seconds")
            print(str(diff) + " field lineups successfully generated")
            # print("Reject counters:", dict(overall_reject_counters))

            # print(self.field_lineups) 
            return self.field_lineups  # or whatever variable holds the generated lineups
        
    def generate_lineup_matrix(self, fields):
        # Extracting all unique player IDs from the fields
        all_players = sorted(list(self.id_name_dict.keys()))
        player_indices = {player: idx for idx, player in enumerate(all_players)}
        
        num_fields = len(fields)
        num_lineups = max(len(field) for field in fields)  # Getting the maximum number of lineups in any field
        num_players = len(all_players)
        
        lineup_matrix = np.zeros((num_fields, num_lineups, num_players), dtype=int)
        
        for field_idx, field in enumerate(fields):
            for lineup_idx, lineup_info in enumerate(field.values()):
                lineup = lineup_info['Lineup']
                for player in lineup:
                    player_idx = player_indices[player]
                    lineup_matrix[field_idx, lineup_idx, player_idx] = 1
        
        self.fields_matrix = lineup_matrix
        return lineup_matrix



    def calc_gamma(self, mean, sd):
        alpha = (mean / sd) ** 2
        beta = sd**2 / mean
        return alpha, beta

    @staticmethod
    def run_simulation_for_game(
        team1_id,
        team1,
        team2_id,
        team2,
        qb_samples_dict,
        num_iterations,
        roster_construction,
    ):
        # Define correlations between positions

        def get_corr_value(player1, player2):
            # If players are on the same team and have the same position
            if (
                player1["Team"] == player2["Team"]
                and player1["Position"][0] == player2["Position"][0]
            ):
                return -0.25

            if player1["Team"] != player2["Team"]:
                player_2_pos = "Opp " + str(player2["Position"][0])
            else:
                player_2_pos = player2["Position"][0]

            # Fetch correlation value based on player1's primary position for player2's primary position
            return player1["Correlations"][player_2_pos]

        def build_covariance_matrix(players):
            N = len(players)
            matrix = [[0 for _ in range(N)] for _ in range(N)]
            corr_matrix = [[0 for _ in range(N)] for _ in range(N)]

            for i in range(N):
                for j in range(N):
                    if i == j:
                        matrix[i][j] = (
                            players[i]["StdDev"] ** 2
                        )  # Variance on the diagonal
                        corr_matrix[i][j] = 1
                    else:
                        matrix[i][j] = (
                            get_corr_value(players[i], players[j])
                            * players[i]["StdDev"]
                            * players[j]["StdDev"]
                        )
                        corr_matrix[i][j] = get_corr_value(players[i], players[j])
            return matrix, corr_matrix

        def ensure_positive_semidefinite(matrix):
            eigs = np.linalg.eigvals(matrix)
            if np.any(eigs < 0):
                jitter = abs(min(eigs)) + 1e-6  # a small value
                matrix += np.eye(len(matrix)) * jitter
            return matrix

        game = team1 + team2
        covariance_matrix, corr_matrix = build_covariance_matrix(game)
        # print(team1_id, team2_id)
        # print(corr_matrix)
        corr_matrix = np.array(corr_matrix)

        # Given eigenvalues and eigenvectors from previous code
        eigenvalues, eigenvectors = np.linalg.eigh(covariance_matrix)

        # Set negative eigenvalues to zero
        eigenvalues[eigenvalues < 0] = 0

        # Reconstruct the matrix
        covariance_matrix = eigenvectors.dot(np.diag(eigenvalues)).dot(eigenvectors.T)

        try:
            samples = multivariate_normal.rvs(
                mean=[player["Fpts"] for player in game],
                cov=covariance_matrix,
                size=num_iterations,
            )
        except:
            print(team1_id, team2_id, "bad matrix")

        player_samples = []
        for i, player in enumerate(game):
            if "QB" in player["Position"]:
                sample = samples[:, i]
            else:
                sample = samples[:, i]
            # if player['Team'] in ['LAR','SEA']:
            #     print(player['Name'], player['Fpts'], player['StdDev'], sample, np.mean(sample), np.std(sample))
            player_samples.append(sample)

        temp_fpts_dict = {}
        # print(team1_id, team2_id, len(game), uniform_samples.T.shape, len(player_samples), covariance_matrix.shape )

        for i, player in enumerate(game):
            temp_fpts_dict[player["ID"]] = player_samples[i]

        # fig, (ax1, ax2, ax3,ax4) = plt.subplots(4, figsize=(15, 25))
        # fig.tight_layout(pad=5.0)

        # for i, player in enumerate(game):
        #     sns.kdeplot(player_samples[i], ax=ax1, label=player['Name'])

        # ax1.legend(loc='upper right', fontsize=14)
        # ax1.set_xlabel('Fpts', fontsize=14)
        # ax1.set_ylabel('Density', fontsize=14)
        # ax1.set_title(f'Team {team1_id}{team2_id} Distributions', fontsize=14)
        # ax1.tick_params(axis='both', which='both', labelsize=14)

        # y_min, y_max = ax1.get_ylim()
        # ax1.set_ylim(y_min, y_max*1.1)

        # ax1.set_xlim(-5, 50)

        # # # Sorting players and correlating their data
        # player_names = [f"{player['Name']} ({player['Position']})" if player['Position'] is not None else f"{player['Name']} (P)" for player in game]

        # # # Ensuring the data is correctly structured as a 2D array
        # sorted_samples_array = np.array(player_samples)
        # if sorted_samples_array.shape[0] < sorted_samples_array.shape[1]:
        #     sorted_samples_array = sorted_samples_array.T

        # correlation_matrix = pd.DataFrame(np.corrcoef(sorted_samples_array.T), columns=player_names, index=player_names)

        # sns.heatmap(correlation_matrix, annot=True, ax=ax2, cmap='YlGnBu', cbar_kws={"shrink": .5})
        # ax2.set_title(f'Correlation Matrix for Game {team1_id}{team2_id}', fontsize=14)

        # original_corr_matrix = pd.DataFrame(corr_matrix, columns=player_names, index=player_names)
        # sns.heatmap(original_corr_matrix, annot=True, ax=ax3, cmap='YlGnBu', cbar_kws={"shrink": .5})
        # ax3.set_title(f'Original Correlation Matrix for Game {team1_id}{team2_id}', fontsize=14)

        # cov_matrix = pd.DataFrame(covariance_matrix, columns=player_names, index=player_names)
        # sns.heatmap(cov_matrix, annot=True, ax=ax4, cmap='YlGnBu', cbar_kws={"shrink": .5})
        # ax4.set_title(f'Original Covariance Matrix for Game {team1_id}{team2_id}', fontsize=14)

        # plt.savefig(f'output/Team_{team1_id}{team2_id}_Distributions_Correlation.png', bbox_inches='tight')
        # plt.close()

        return temp_fpts_dict


    def run_tournament_simulation(self):
        print("Running " + str(self.num_iterations) + " simulations")
        
        start_time = time.time()
        temp_fpts_dict = {}
        qb_samples_dict = {}  # keep track of already simmed quarterbacks
        size = self.num_iterations
        game_simulation_params = []
        print("Preparing game simulation parameters...")  # Added print statement
        for m in self.matchups:
            game_simulation_params.append(
                (
                    m[0],
                    self.teams_dict[m[0]],
                    m[1],
                    self.teams_dict[m[1]],
                    qb_samples_dict,
                    self.num_iterations,
                    self.roster_construction,
                )
            )
        print("Starting multiprocessing pool...")  # Added print statement
        with mp.Pool() as pool:
            results = pool.starmap(self.run_simulation_for_game, game_simulation_params)

        print("Updating temp_fpts_dict with simulation results...")  # Added print statement
        for res in results:
            temp_fpts_dict.update(res)
            # print(temp_fpts_dict)  # Print the temp_fpts_dict after each update
        
        print("Finished running simulations in %s seconds" % (time.time() - start_time))  # Added print statement
        self.temp_fpts_dict = temp_fpts_dict  # set the instance variable
        


        
    def calculate_lineup_scores_matrix(self):
        player_scores_dict = self.temp_fpts_dict
        # print(self.id_name_dict)
        # The shape of the fields_matrix should be (num_fields, num_lineups, num_players)
        num_fields, num_lineups, _ = self.fields_matrix.shape
        
        # Creating a matrix to hold the scores of the lineups in each field
        lineup_scores_matrix = np.zeros((num_fields, num_lineups, self.num_iterations))
        
        for field_index in range(num_fields):
            for lineup_index in range(num_lineups):
                player_lineup_binary = self.fields_matrix[field_index, lineup_index, :]
                # print("Length of player_lineup_binary:", len(player_lineup_binary))
                # print("Length of id_name_dict:", len(self.id_name_dict))

                all_player_ids = sorted(list(self.id_name_dict.keys()))  # Ensure the order is the same as in generate_lineup_matrix
                for sim_index in range(self.num_iterations):
                    total_score = 0
                    for player_index, player_id in enumerate(all_player_ids):
                        if player_index < len(player_lineup_binary) and player_lineup_binary[player_index] == 1:
                            player_score = player_scores_dict.get(player_id, [0] * self.num_iterations)[sim_index]
                            # print(f"Player ID: {player_id}, Player Name: {self.id_name_dict[player_id]}, Score: {player_score}")
                            total_score += player_score
                            
                        # After calculating total_score for a lineup, print it for verification
                    # print(f"Total Score for field {field_index}, lineup {lineup_index}, sim {sim_index}: {total_score}")
                        
                    lineup_scores_matrix[field_index, lineup_index, sim_index] = total_score
                            
        # Print the shape of the matrix
        print("Shape of lineup_scores_matrix:", lineup_scores_matrix.shape)
        
        # Print some statistics
        print("Average score in lineup_scores_matrix:", np.mean(lineup_scores_matrix))
        print("Minimum score in lineup_scores_matrix:", np.min(lineup_scores_matrix))
        print("Maximum score in lineup_scores_matrix:", np.max(lineup_scores_matrix))
        
        # # Optionally print a small portion of the matrix
        # print("Portion of lineup_scores_matrix:")
        # print(lineup_scores_matrix[:2, :2, :2])  # Adjust indices to print a different portion
        
        return lineup_scores_matrix



    def generate_personal_pool_matrix(self):
        # Get the personal pool of lineups
        personal_pool = self.generate_pool_lineups()
        
        # Extract all unique player IDs and create a dictionary mapping player IDs to indices
        all_players = sorted(list(self.id_name_dict.keys()))
        player_indices = {player: idx for idx, player in enumerate(all_players)}
        
        # Initialize the personal pool matrix
        num_lineups = len(personal_pool)
        num_players = len(all_players)
        personal_pool_matrix = np.zeros((num_lineups, num_players), dtype=int)
        
        # Convert each lineup to binary and store in the matrix
        for lineup_idx, lineup_info in personal_pool.items():
            lineup = lineup_info['Lineup']
            for player in lineup:
                player_idx = player_indices[player]
                personal_pool_matrix[lineup_idx, player_idx] = 1
        # print(personal_pool_matrix)        
        return personal_pool_matrix


    def calculate_personal_pool_scores(self):
        player_scores_dict = self.temp_fpts_dict
        
        # Get the personal pool matrix
        personal_pool_matrix = self.generate_personal_pool_matrix()
        num_lineups, _ = personal_pool_matrix.shape
        
        # Creating a matrix to hold the scores of the lineups in personal pool
        personal_pool_scores_matrix = np.zeros((num_lineups, self.num_iterations))
        
        all_player_ids = sorted(list(self.id_name_dict.keys()))  # Ensure the order is the same as in generate_personal_pool_matrix
        
        for lineup_index in range(num_lineups):
            player_lineup_binary = personal_pool_matrix[lineup_index, :]
            
            for sim_index in range(self.num_iterations):
                total_score = 0
                for player_index, player_id in enumerate(all_player_ids):
                    if player_lineup_binary[player_index] == 1:
                        player_score = player_scores_dict.get(player_id, [0] * self.num_iterations)[sim_index]
                        total_score += player_score
                
                personal_pool_scores_matrix[lineup_index, sim_index] = total_score
        
        # Print the shape of the matrix
        print("Shape of personal_pool_scores_matrix:", personal_pool_scores_matrix.shape)
        
        # Print some statistics
        print("Average score in personal_pool_scores_matrix:", np.mean(personal_pool_scores_matrix))
        print("Minimum score in personal_pool_scores_matrix:", np.min(personal_pool_scores_matrix))
        print("Maximum score in personal_pool_scores_matrix:", np.max(personal_pool_scores_matrix))
        
        # Optionally print a small portion of the matrix
        print("Portion of personal_pool_scores_matrix:")
        print(personal_pool_scores_matrix[:2, :2])  # Adjust indices to print a different portion
        
        return personal_pool_scores_matrix



    def save_lineups_with_performance_to_csv(self, lineups, performance_summary):
        # Specify the path where the CSV will be saved
        out_path = os.path.join(os.path.dirname(__file__),
                                "../output/{}_gpp_sim_lineups_with_performance_{}_{}.csv".format(self.site, self.field_size, self.num_iterations))

        # Specify the headers of the CSV
        headers = ['QB', 'RB1', 'RB2', 'WR1', 'WR2', 'WR3', 'TE', 'FLEX', 'DST', 'ROI', 'Win%', 'Top 10%']

        with open(out_path, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(headers)  # Write the headers
            
            # Iterate over the lineups in self.pool_lineups and write each lineup's players and performance metrics
            for lineup_index, lineup_info in self.pool_lineups.items():
                # Assume lineup_array is in the order ['DST', 'QB', 'RB1', 'RB2', 'WR1', 'WR2', 'WR3', 'TE', 'FLEX']
                lineup_array = np.array(lineup_info['Lineup'])  # Convert to NumPy array to ensure consistent handling

                # Correct the order of lineup_array to ['QB', 'RB1', 'RB2', 'WR1', 'WR2', 'WR3', 'TE', 'FLEX', 'DST']
                correct_order_indices = [1, 2, 3, 4, 5, 6, 7, 8, 0]
                corrected_lineup_array = lineup_array[correct_order_indices]
                
                formatted_lineup = [f"{self.id_name_dict[str(player_id)]} ({player_id})" for player_id in corrected_lineup_array]
                
                # Get the performance metrics for this lineup
                lineup_performance = performance_summary[lineup_index]
                performance_metrics = [lineup_performance[metric] for metric in ['ROI', 'Win%', 'Top 10%']]
                
                # Combine the formatted lineup and performance metrics to write to the CSV
                writer.writerow(formatted_lineup + performance_metrics)
        print(f"Lineups with performance metrics written to {out_path}")


    def evaluate_personal_pool_performance(self):
        personal_pool_scores_matrix = self.calculate_personal_pool_scores()
        lineup_scores_matrix = self.calculate_lineup_scores_matrix()

        num_lineups, num_sims = personal_pool_scores_matrix.shape
        num_fields, num_field_lineups, _ = lineup_scores_matrix.shape
        
        performance_summary = []  # Now a list instead of a dictionary
        
        total_entry_fees = num_fields * self.entry_fee  # Total entry fees paid across all fields

        for lineup_index in range(num_lineups):
            # Initialize a dictionary to hold the performance of this lineup
            lineup_performance = {
                'Lineup': lineup_index,
                'ROI': 0,
                'Win%': 0,
                'Top 10%': 0
            }
            
            for sim_index in range(num_sims):
                total_winnings = 0  # Total winnings across all fields in this simulation
                wins = 0  # Number of wins across all fields in this simulation
                top_10_percent_count = 0  # Number of times in the top 10% across all fields in this simulation

                for field_index in range(num_fields):
                    # Get the scores of the field lineups and the current personal pool lineup for this simulation
                    all_scores = np.concatenate((lineup_scores_matrix[field_index, :, sim_index], [personal_pool_scores_matrix[lineup_index, sim_index]]))
                    sorted_indices = np.argsort(all_scores)[::-1]  # Sort in descending order to rank the lineups
                    top_10_percent_index = int(len(sorted_indices) * 0.1)  # Index for the top 10% of lineups

                    rank = np.where(sorted_indices == num_field_lineups)[0][0]
                    if rank < len(self.payout_structure):
                        total_winnings += self.payout_structure[rank]
                    if rank == 0:
                        wins += 1
                    if rank <= top_10_percent_index:
                        top_10_percent_count += 1

                lineup_performance['ROI'] += (total_winnings - total_entry_fees) / total_entry_fees * 100 / num_sims
                lineup_performance['Win%'] += wins / num_fields * 100 / num_sims
                lineup_performance['Top 10%'] += top_10_percent_count / num_fields * 100 / num_sims
            
            # Append this lineup's performance to the summary
            performance_summary.append(lineup_performance)
        
         # Calculate the average performance across all simulations
        average_performance = {metric: np.mean([lineup[metric] for lineup in performance_summary]) for metric in ['ROI', 'Win%', 'Top 10%']}

        print("Average Performance:")
        print(average_performance)
        self.save_lineups_with_performance_to_csv(self.pool_lineups, performance_summary)

        return performance_summary, average_performance

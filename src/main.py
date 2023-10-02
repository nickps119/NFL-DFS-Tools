import sys
from windows_inhibitor import *
from nfl_showdown_optimizer import *
from nfl_optimizer import *

def main(arguments):
    if len(arguments) < 3 or len(arguments) > 9:
        print('Incorrect usage. Please see `README.md` for proper usage.')
        exit()

    site = arguments[1]
    process = arguments[2]

    if process == 'opto':
        num_lineups = arguments[3]
        num_uniques = arguments[4]
        opto = NFL_Optimizer(site, num_lineups, num_uniques)
        opto.optimize()
        opto.output()

    elif process == 'sd_opto':
        num_lineups = arguments[3]
        num_uniques = arguments[4]
        opto = NFL_Showdown_Optimizer(site, num_lineups, num_uniques)
        opto.optimize()
        opto.output()
    
    elif process == 'sd_sim':
        import nfl_showdown_simulator
        field_size = -1
        num_iterations = -1
        use_contest_data = False
        use_file_upload = False
        match_lineup_input_to_field_size = True
        if arguments[3] == 'cid':
            use_contest_data = True
        else:
            field_size = arguments[3]

        if arguments[4] == 'file':
            use_file_upload = True
            num_iterations = arguments[5]
        else:
            num_iterations = arguments[4]
        #if 'match' in arguments:
        #    match_lineup_input_to_field_size = True
        sim = nfl_showdown_simulator.NFL_Showdown_Simulator(site, field_size, num_iterations, use_contest_data,
                                use_file_upload)
        sim.generate_field_lineups()
        sim.run_tournament_simulation()
        sim.save_results()
        

    elif process == 'sim':
        import nfl_gpp_simulator_modified as nfl_gpp_simulator
        site = arguments[1]
        pool_size = arguments[3]
        field_size = -1
        num_iterations = -1
        num_fields = -1
        use_contest_data = False
        use_file_upload = False
        use_lineup_input = False
        match_lineup_input_to_field_size = True
        if arguments[4] == 'cid':
            use_contest_data = True
            num_fields = int(arguments [5])
        else:
            field_size = int(arguments[4])
            num_fields = int(arguments [5])

        if arguments[6] == 'file':
            use_file_upload = True
            num_iterations = arguments[7]
        else:
            num_iterations = arguments[6]
        #if 'match' in arguments:
        #    match_lineup_input_to_field_size = True


        sim = nfl_gpp_simulator.NFL_GPP_Simulator_Modified(site, pool_size, field_size, num_fields, num_iterations, use_contest_data, use_file_upload)
        # sim.generate_pool_lineups()
        fields = []  # A list to store the generated fields
        for i in range(num_fields):  # num_fields should be the number of fields you want to generate
            field = sim.generate_field_lineups()  # Replace with the actual method used to generate a field of lineups
            # print(f'Field {i + 1}: {field}')
            fields.append(field)
            print("Added field", {i + 1}, "to the list of fields.")
            sim.field_lineups = {}  # Reset the field_lineups for the next iteration
        # print(fields)
        sim.generate_lineup_matrix(fields)
        sim.run_tournament_simulation()
        # sim.calculate_lineup_scores_matrix()
        # sim.calculate_personal_pool_scores()
        sim.evaluate_personal_pool_performance()
        # sim.output()
        

if __name__ == "__main__":
    main(sys.argv)
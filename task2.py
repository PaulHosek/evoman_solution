# --------------------- Import Frameworks and Libraries ---------------------- #
import random
import pickle
import operator
import sys, os
import utils
import numpy as np
import pandas as pd
import multiprocessing as mp

from deap import tools, creator, base, algorithms
from os import environ
from deap import cma

sys.path.insert(0, 'evoman_fast')
from environment import Environment
from demo_controller import player_controller

# Create experiment folder if needed
experiment_name = 'task2'
if not os.path.exists(experiment_name + '/exp_results'):
    os.makedirs(experiment_name + '/exp_results/exp_results')
    os.makedirs(experiment_name + '/exp_results/best_results')
    os.makedirs(experiment_name + '/exp_results/best_results' + '/best_weights')
    os.makedirs(experiment_name + '/exp_results/best_results' + '/best_individuals')
    os.makedirs(experiment_name + '/exp_results/pickle')
    os.makedirs(experiment_name + '/exp_results/plots')

# Prevent graphics and audio rendering to speed up simulations
os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = 'hide'

# Read environment variables
NRUN = int(environ.get("nrun", 1))
enemies = list(map(int, environ.get("enemy", '1-3-4-6-7').split('-')))
MU = int(environ.get("mu", 23))
LAMBDA = int(environ.get("lambda", 114))
SIGMA = float(environ.get("sigma", 0.122))
NGEN = int(environ.get("ngen", 400))
multiple_mode = 'yes' if len(enemies) > 1 else 'no'
n_hidden_neurons = 10
strategy = environ.get("strategy", 'cma')
checkpoint = False
loadFromOne = False

# Initialise the game environment for the chosen settings
env = Environment(experiment_name=experiment_name,
                  enemies=enemies,
                  multiplemode=multiple_mode,
                  playermode="ai",
                  player_controller=player_controller(n_hidden_neurons),
                  enemymode="static",
                  level=2,
                  randomini="yes",
                  speed="fastest")

# -------------------------------- Functions For DEAP ------------------------- #
# a game simulation for environment env and game x
def simulation(x):
    results = env.play(pcont=x)
    return results

# evaluation of game
def cust_evaluate(indiv):
    fitness, player_life, enemy_life, game_time = simulation(indiv)
    return (fitness,)

# evaluation of an Individual weights when playing against enemies
# we need all fitness values to send for the MO strategy
def cust_evaluate_mo(indiv):
    mo_fitness = []
    for idx, enemy in enumerate(enemies):
        fit, _, _, _ = env.run_single(enemy, pcont=np.array(indiv), econt="None")
        mo_fitness.append(fit)
    # we return a tuple of size len(enemies) with the fitness values after each game
    return tuple(mo_fitness)

# Needed for HOF
def eq_(var1, var2):
    return operator.eq(var1, var2).all()

def mean_mo(fit):
    enemy_mean = np.mean(fit, axis=1)
    enemy_std = np.std(fit, axis=1)
    cons_fit = np.subtract(enemy_mean, enemy_std)
    mean_cons_fit = np.mean(cons_fit)
    return mean_cons_fit

def max_mo(fit):
    enemy_mean = np.mean(fit, axis=1)
    enemy_std = np.std(fit, axis=1)
    cons_fit = np.subtract(enemy_mean, enemy_std)
    max_cons_fit = np.max(cons_fit)
    return max_cons_fit

# ----------------------------- Initialise DEAP ------------------------------ #

n_weights = (env.get_num_sensors() + 1) * n_hidden_neurons + (n_hidden_neurons + 1) * 5

if hasattr(creator, "FitnessMax"):
    del creator.FitnessMax
if hasattr(creator, "FitnessMulti"):
    del creator.FitnessMulti
if hasattr(creator, "Individual"):
    del creator.Individual

toolbox = base.Toolbox()
if strategy == 'cma-mo':
    # create the fitness attribute of an Individual as a tuple of size len(enemies)
    # we will not have one fitness value as before to maximize, but len(enemies) fitness values
    # these are our objectives - the fitness values for playing against each enemy from the enemies list
    # i.e.: for 3 enemies, weights(or fitness) will be a tuple(1.0,1.0,1.0)
    creator.create("FitnessMulti", base.Fitness, weights=(1.0,) * len(enemies))
    creator.create("Individual", np.ndarray, fitness=creator.FitnessMulti, player_life=100, enemy_life=100)
    toolbox.register("evaluate", cust_evaluate_mo)
else:
    creator.create("FitnessMax", base.Fitness, weights=(1.0,))
    creator.create('Individual', np.ndarray, fitness=creator.FitnessMax, player_life=100, enemy_life=100)
    toolbox.register("evaluate", cust_evaluate)

if strategy == 'cma-mo':
    #stats.register("mean", mean_mo)
    #stats.register("max", max_mo)
    stats = tools.Statistics()
    stats.register("mean", lambda pop: np.mean([np.mean(ind.fitness.values) for ind in pop]))
    stats.register("max", lambda pop: np.max([np.mean(ind.fitness.values) for ind in pop]))

else:
    # Register statistics functions
    stats = tools.Statistics(lambda ind: ind.fitness.values)
    stats.register("mean", np.mean)
    stats.register("max", np.max)

# ---------------------------------- Main ------------------------------------ #
def main():
    best_individuals = []
    statistics = []

    pool = mp.Pool(processes=mp.cpu_count())
    toolbox.register("map", pool.map)
    # We run the experiment a few times - n_runs
    for run in range(1, NRUN + 1):
        print(f"{strategy} strategy -- Start of evolution enemies {enemies} run {run}")
        exp_name = f"{MU}_{LAMBDA}_{NGEN}"

        if run > 1:
            toolbox.unregister("generate")
            toolbox.unregister("update")
        # TO-DO: add seed for reproducibility
        if strategy == 'cma-mo':
            # Generate population of MU individuals from an Uniform distribution -1, 1 with n_weights
            population = [creator.Individual(x) for x in (np.random.uniform(-1, 1, (MU, n_weights)))]
            # We evaluate the initial population and update its fitness
            fitnesses = toolbox.map(toolbox.evaluate, population)
            for ind, fit in zip(population, fitnesses):
                ind.fitness.values = fit
            # We initialize the MO strategy
            cma_strategy = cma.StrategyMultiObjective(population, sigma=SIGMA, mu=MU, lambda_=LAMBDA)
        elif strategy == 'cma-opl':
            parent = creator.Individual(np.random.uniform(-1, 1, n_weights))
            parent.fitness.values = toolbox.evaluate(parent)
            cma_strategy = cma.StrategyOnePlusLambda(parent, sigma=SIGMA, lambda_=LAMBDA)
        else:
            cma_strategy = cma.Strategy(centroid=np.random.uniform(-1, 1, n_weights), sigma=SIGMA, mu=MU,
                                        lambda_=LAMBDA)

        toolbox.register("generate", cma_strategy.generate, creator.Individual)
        toolbox.register("update", cma_strategy.update)

        hof = tools.ParetoFront(eq_)
        # generate new population + update its value with methods in toolbox
        # logbook = statistics of the evolution
        if strategy == 'cma' and checkpoint:
            if loadFromOne:
                weights = np.loadtxt(experiment_name + '/exp_results/best_start.txt')
                pop = []
                for i in range(0, LAMBDA):
                    if i > 0:
                        mask = np.random.uniform(-0.1, 0.1, n_weights)
                        masked_weights = np.add(weights, mask)
                        pop.append(creator.Individual(masked_weights))
                    else:
                        pop.append(creator.Individual(weights))
            else:
                # A file name has been given, then load the data from the file
                with open(f"{experiment_name}/exp_results/pickle/exp-{exp_name}_alg-{strategy}_enemy-{str(enemies)}_run-{run}.pkl", "rb") as cp_file:
                    cp = pickle.load(cp_file)
                pop = cp["population"]
                hof = cp["halloffame"]
                hof.update(pop)

            # Evaluate the individuals
            fitnesses = toolbox.map(toolbox.evaluate, pop)
            for ind, fit in zip(pop, fitnesses):
                ind.fitness.values = fit
            toolbox.update(pop)
            record = stats.compile(pop) if stats is not None else {}
            logbook = tools.Logbook()
            logbook.header = ['gen', 'nevals'] + (stats.fields if stats else [])
            logbook.record(gen=0, nevals=len(pop), **record)
            print(logbook.stream)

            for gen in range(1, NGEN):
                # Generate a new population
                pop = toolbox.generate()
                # Evaluate the individuals
                fitnesses = toolbox.map(toolbox.evaluate, pop)
                for ind, fit in zip(pop, fitnesses):
                    ind.fitness.values = fit

                if hof is not None:
                    hof.update(pop)

                # Update the strategy with the evaluated individuals
                toolbox.update(pop)

                record = stats.compile(pop) if stats is not None else {}
                logbook.record(gen=gen, nevals=len(pop), **record)
                print(logbook.stream)
        else:
            pop, logbook = algorithms.eaGenerateUpdate(toolbox, ngen=NGEN, stats=stats, halloffame=hof)

        best_individuals.append(hof[0])
        statistics.append(pd.DataFrame(logbook))

        print("-- End of (successful) evolution --")

        # Write best individuals fitness values for enemy and experiment
        utils.plot_exp_stats(statistics, experiment_name + "/exp_results/plots/", exp_name, strategy, str(enemies), NGEN)
        utils.write_best(best_individuals, experiment_name + "/exp_results/best_results/best_weights/", exp_name, strategy, str(enemies))
        utils.eval_best(env, best_individuals, experiment_name + "/exp_results/best_results/best_individuals/", exp_name, strategy, str(enemies))

        cp = dict(population=pop, generation=NGEN, halloffame=hof)
        with open(f"{experiment_name}/exp_results/pickle/exp-{exp_name}_alg-{strategy}_enemy-{str(enemies)}_run-{run}.pkl", "wb") as cp_file:
            pickle.dump(cp, cp_file)
    pool.close()

if __name__ == "__main__":
    main()
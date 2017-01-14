# coding=utf-8
# 1060,done, took 2729.434 seconds
# k-80,done, took 11504.376 seconds
from __future__ import division
import argparse
#z
from PIL import Image
import numpy as np
import gym

from keras.models import Sequential
from keras.layers import Dense, Activation, Flatten, Convolution2D, Permute, LSTM, Reshape, Merge, Dropout, Highway
from keras.optimizers import Adam
import keras.backend as K

from rl.agents.dqn import DQNAgent
from rl.policy import LinearAnnealedPolicy, BoltzmannQPolicy, EpsGreedyQPolicy
from rl.memory import SequentialMemory
from rl.core import Processor
from rl.callbacks import FileLogger, ModelIntervalCheckpoint, TrainIntervalLogger
from keras.callbacks import Callback
import financial_env
import financial_env_for_simulation

price_len = 20

# input_data size (20+2)*1
INPUT_SHAPE = (2 + price_len, 1)  ##need to have some way to normalize the last 2 dimension
WINDOW_LENGTH = 1


class financialProcessor(Processor):
    def process_observation(self, observation):
        if np.asarray(observation).shape[0] == 4:
            return observation[0]
        return observation


parser = argparse.ArgumentParser()
parser.add_argument('--mode', choices=['train', 'test'], default='train')
parser.add_argument('--env-name', type=str, default='sin_data')
parser.add_argument('--training-path', type=str, default='EURUSD60_train.csv')
parser.add_argument('--testing-path', type=str, default='EURUSD60_test.csv')
parser.add_argument('--env-params', type=str, default='points=' + str(price_len) + ',dt=0.05,sin_index=0,noise=0,hold_num=0,Account_All=3000,lossRate=0.6,max=5000')
parser.add_argument('--weights', type=str, default=None)
parser.add_argument('--update', type=str, default='n')
args = parser.parse_args()

# Get the environment and extract the number of actions.
if args.env_name == 'sin_data':
    env = financial_env_for_simulation.simulationEnv(args.env_params)
else:
    env = financial_env.financialEnv(args.env_params, args.training_path)
np.random.seed(123)
# env.seed(123)
nb_actions = env.action_space.n

# We patch the environment to be closer to what Mnih et al. actually do: The environment
# repeats the action 4 times and a game is considered to be over during training as soon as a live
# is lost.
# def _step(a):
#     reward = 0.0
#     action = env._action_set[a]
#     lives_before = env.ale.lives()
#     for _ in range(4):
#         reward += env.ale.act(action)
#     ob = env._get_obs()
#     done = env.ale.game_over() or (args.mode == 'train' and lives_before != env.ale.lives())
#     return ob, reward, done, {}
# env._step = _step

# Next, we build our model. We use the same model that was described by Mnih et al. (2015).
input_shape = (WINDOW_LENGTH,) + INPUT_SHAPE
print input_shape
dropout_rate = 0.5
num_layers = 3
model = Sequential()
if K.image_dim_ordering() == 'tf':
    # (width, height, channels)
    model.add(Permute((2, 3, 1), input_shape=input_shape))
elif K.image_dim_ordering() == 'th':
    # (channels, width, height)
    model.add(Permute((1, 2, 3), input_shape=input_shape))
else:
    raise RuntimeError('Unknown image_dim_ordering.')
# model.add(Convolution2D(32, 8, 1, subsample=(4, 4)))
# model.add(Activation('relu'))
# model.add(Convolution2D(64, 4, 1, subsample=(2, 2)))


#####need to figure out how to provide two inputs
# price_model=Sequential()
##price_model.add(Reshape(INPUT_SHAPE, input_shape=input_shape)) ###change
# input_shape1=(price_len,1)
# price_model.add(Permute((2, 1), input_shape=input_shape1))
# price_model.add(LSTM(64))
#
#
# holding_model=Sequential()
# input_shape2=(input_shape[0]-price_len,1)
# holding_model.add(Permute((2, 1), input_shape=input_shape2 ))
##price_model.add(Reshape(INPUT_SHAPE, input_shape=input_shape)) ###change
# holding_model.add(Dense(10 ))
# holding_model.add(Activation('relu'))
# holding_model.add(Flatten())
#
# model = Sequential()
# model.add(Merge([price_model, holding_model], mode='concat'))
# model.add(Reshape(INPUT_SHAPE, input_shape=input_shape))
# model.add(LSTM(64))


useHighway = True

if useHighway:
    model.add(Dense(5))
    model.add(Flatten())
    for index in range(num_layers):
        model.add(Highway(activation='relu'))
        model.add(Dropout(dropout_rate))
else:  # CNN
    model.add(Convolution2D(32, 8, 1, subsample=(4, 4)))
    model.add(Activation('relu'))
    model.add(Convolution2D(64, 4, 1, subsample=(2, 2)))
    model.add(Activation('relu'))
    model.add(Flatten())
    model.add(Dense(51))
    model.add(Activation('relu'))

model.add(Dense(nb_actions))
model.add(Activation('softmax'))
# model.add(Activation('linear'))
print(model.summary())

# Finally, we configure and compile our agent. You can use every built-in Keras optimizer and
# even the metrics!
memory = SequentialMemory(limit=1000000, window_length=WINDOW_LENGTH)
processor = financialProcessor()

# Select a policy. We use eps-greedy action selection, which means that a random action is selected
# with probability eps. We anneal eps from 1.0 to 0.1 over the course of 1M steps. This is done so that
# the agent initially explores the environment (high eps) and then gradually sticks to what it knows
# (low eps). We also set a dedicated eps value that is used during testing. Note that we set it to 0.05
# so that the agent still performs some random actions. This ensures that the agent cannot get stuck.
policy = LinearAnnealedPolicy(EpsGreedyQPolicy(), attr='eps', value_max=1., value_min=.1, value_test=.05,
                              nb_steps=1000000)

# The trade-off between exploration and exploitation is difficult and an on-going research topic.
# If you want, you can experiment with the parameters or use a different policy. Another popular one
# is Boltzmann-style exploration:
# policy = BoltzmannQPolicy(tau=1.)
# Feel free to give it a try!

dqn = DQNAgent(model=model, nb_actions=nb_actions, policy=policy, memory=memory,
               processor=processor, nb_steps_warmup=50000, gamma=.99, delta_range=(-1., 1.),
               target_model_update=10000, train_interval=4)
dqn.compile(Adam(lr=.00025), metrics=['mae'])

class eps_History(Callback):
    def __init__(self, interval=10000):
        self.interval = interval
        self.step = 0
        self.reward_list=[]
        self.action_list=[]
        self.price=env.price
        self.reset()

    def reset(self):
        self.maxdown=10000
        self.maxdown_action=0
        self.p_reward=0
        self.n_reward=0
        self.T_reward=0.0
        self.episode_rewards = []

    def on_step_begin(self, step, logs):
        if self.step % self.interval == 0:
            # print "*-*----*-*-*-*-*-*-*-*-*-*-"
            # print len(self.episode_rewards)
            if len(self.episode_rewards) > 0:
                print "+/- rewards are",self.p_reward," / ",self.n_reward," / ",self.p_reward/(self.p_reward+self.n_reward+0.00001)
                print "total reward is ",self.T_reward
                print "average reward is ",self.T_reward/self.interval
                print "maxdown is ",self.maxdown
                print "maxdown action is ",self.maxdown_action
                # print self.price.__len__()
                print ''
            self.reset()


    def on_step_end(self, step, logs):
        self.step += 1
        self.reward_list.append(logs['reward'])
        self.action_list.append(logs['action'])
        if logs['reward']>0:
            self.p_reward=self.p_reward+1
        if logs['reward']<0:
            self.n_reward=self.n_reward+1
        self.T_reward=self.T_reward+logs['reward']
        if self.step>2:
            if self.reward_list[step]-self.reward_list[step-1]<self.maxdown:
                self.maxdown=self.reward_list[step]-self.reward_list[step-1]
                self.maxdown_action=self.action_list[step]

    def on_episode_end(self, episode, logs):
        self.episode_rewards.append(logs['episode_reward'])


if args.mode == 'train':
    # Okay, now it's time to learn something! We capture the interrupt exception so that training
    # can be prematurely aborted. Notice that you can the built-in Keras callbacks!
    weights_filename = 'dqn_{}_weights.h5f'.format(args.env_name)
    checkpoint_weights_filename = 'dqn_' + args.env_name + '_weights_{step}.h5f'
    log_filename = 'dqn_{}_log.json'.format(args.env_name)
    res=eps_History(interval=60000)
    callbacks = [ModelIntervalCheckpoint(checkpoint_weights_filename, interval=2500000)]
    callbacks += [FileLogger(log_filename, interval=100)]
    callbacks += [res]

    if args.update == 'y':
        if args.weights:
            weights_filename = args.weights
        dqn.load_weights(weights_filename)
    dqn.fit(env, callbacks=callbacks, nb_steps=17500000, log_interval=60000)

    # After training is done, we save the final weights one more time.
    dqn.save_weights(weights_filename, overwrite=True)

    # Finally, evaluate our algorithm for 10 episodes.
    dqn.test(env, nb_episodes=10, visualize=False)
elif args.mode == 'test':
    weights_filename = 'dqn_{}_weights.h5f'.format(args.env_name)
    if args.weights:
        weights_filename = args.weights
    dqn.load_weights(weights_filename)
    dqn.test(env, nb_episodes=10, visualize=False)

    import Gnuplot
    gp = Gnuplot.Gnuplot(persist=3)
    # gp('set terminal x11 size 350,225')
    # gp('set pointsize 2')
    # gp('set yrange [0.0:0.05]')
    plot1 = Gnuplot.PlotItems.Data(env.price_data, with_="linespoints lt rgb 'green' lw 6 pt 1", title="price")
    plot2 = Gnuplot.PlotItems.Data(env.action_data, with_="linespoints lt rgb 'blue' lw 6 pt 1", title="action")
    plot3 = Gnuplot.PlotItems.Data(env.treward_data, with_="linespoints lt rgb 'red' lw 6 pt 1", title="total_reward")
    gp.plot(plot3,plot2, plot1)

    epsFilename = 'result.eps'
    gp.hardcopy(epsFilename, terminal='postscript', enhanced=1, color=1)  # must come after plot() function
    gp.reset()

    #
    # print env.price_data,len(env.price_data)
    # print env.treward_data,len(env.treward_data)
    # print env.action_data,len(env.action_data)

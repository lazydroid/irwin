from collections import namedtuple
from pprint import pprint
from random import shuffle

import logging
import numpy as np
import os.path

from modules.irwin.TrainingStats import TrainingStats, Accuracy, Sample
from modules.irwin.FalseReports import FalseReport

from keras.models import load_model, Model
from keras.layers import Embedding, Dropout, Dense, Reshape, LSTM, Input, concatenate
from keras.optimizers import Adam


class Irwin(namedtuple('Irwin', ['env', 'config'])):
  def gameModel(self):
    if os.path.isfile('modules/irwin/models/game.h5'):
      print("model already exists, opening from file")
      return load_model('modules/irwin/models/game.h5')
    print('model does not exist, building from scratch')
    pvInput = Input(shape=(None, 10), dtype='float32', name='pv_input')
    moveStatsInput = Input(shape=(None, 7), dtype='float32', name='move_input')

    advInput = Input(shape=(None,), dtype='int32', name='advantage_input')
    ranksInput = Input(shape=(None,), dtype='int32', name='ranks_input')
    moveNumberInput = Input(shape=(None,), dtype='int32', name='move_number_input')

    # Embed rank and move number
    a1 = Embedding(input_dim=41, output_dim=32)(advInput)
    r1 = Embedding(input_dim=16, output_dim=8)(ranksInput)
    mn1 = Embedding(input_dim=61, output_dim=32)(moveNumberInput)

    # Merge embeddings
    mnr1 = concatenate([r1, mn1, a1])
    mnr2 = Reshape((-1, 72))(mnr1)

    # analyse PV data (potential moves)
    pv1 = Dense(128, activation='relu')(pvInput)
    pv2 = Dense(64, activation='relu')(pv1)
    d2 = Dropout(0.3)(pv2)
    pv4 = Dense(32, activation='sigmoid')(d2)

    # join rank and move embeddings with move info
    mv0 = concatenate([mnr2, moveStatsInput])

    # analyse move stats and embeddings prior to LSTM
    mv1 = Dense(128, activation='relu')(mv0)
    mv2 = Dense(64, activation='relu')(mv1)
    mv3 = Dense(64, activation='relu')(mv2)
    d3 = Dropout(0.3)(mv3)
    mv4 = Dense(16, activation='sigmoid')(d3)

    # merge move stats with move options
    mvpv = concatenate([mv4, pv4])

    # analyse all the moves and come to a decision about the game
    l1 = LSTM(128, return_sequences=True)(mvpv)
    l2 = LSTM(128, return_sequences=True)(l1)
    l3 = LSTM(64, return_sequences=True)(l2)
    l4 = LSTM(64)(l3)
    l5 = Dense(64, activation='relu')(l4)
    d4 = Dropout(0.3)(l5)
    l6 = Dense(1, activation='sigmoid')(d4)

    secondaryOutput = Dense(1, activation='sigmoid', name='secondary_output')(l3)

    mainOutput = Dense(1, activation='sigmoid', name='main_output')(l6)

    model = Model(inputs=[pvInput, moveStatsInput, moveNumberInput, ranksInput, advInput], outputs=[mainOutput, secondaryOutput])

    model.compile(optimizer=Adam(lr=0.0001),
      loss='binary_crossentropy',
      loss_weights=[1., 0.3],
      metrics=['accuracy'])
    return model

  def train(self):
    # get player sample
    print("getting model")
    model = self.gameModel()
    print("getting dataset")
    batches = self.getTrainingDataset(self.config['train']['batchSize'])
    longest = max([len(b['batch'][0]) for b in batches])

    print("training")
    for x in range(3):
      for b in batches:
        print("Batch Info: Games: " + str(len(b['batch'][0])))
        print("Game Len: " + str(len(b['batch'][2][0])))
        model.fit(b['batch'], b['labels'], epochs=int(self.config['train']['cycles']*len(b['batch'][0])/longest), batch_size=32, validation_split=0.2)
        self.saveGameModel(model)
      shuffle(batches)
    print("complete")

  def saveGameModel(self, model):
    print("saving model")
    model.save('modules/irwin/models/game.h5')

  def getTrainingDataset(self, batchSize):
    print("getting players", end="...", flush=True)
    players = self.env.playerDB.balancedSample(batchSize)
    print(" %d" % len(players))
    print("getting game analyses", end="...", flush=True)
    gameAnalyses = []
    [gameAnalyses.extend(self.env.gameAnalysisDB.byUserId(p.id)) for p in players]
    print(" %d" % len(gameAnalyses))

    print("assigning labels")
    gameLabels = self.assignLabels(gameAnalyses, players)

    print("splitting game analyses datasets")
    cheatGameAnalyses = gameAnalyses[:sum(gameLabels)]
    legitGameAnalyses = gameAnalyses[sum(gameLabels):]

    print("getting moveAnalysisTensors")
    cheatGameTensors = [tga.moveAnalysisTensors() for tga in cheatGameAnalyses]
    legitGameTensors = [tga.moveAnalysisTensors() for tga in legitGameAnalyses]

    print("batching tensors")
    return Irwin.createBatchAndLabels(cheatGameTensors, legitGameTensors)

  def getEvaluationDataset(self, batchSize):
    print("getting players", end="...", flush=True)
    players = self.env.playerDB.balancedSample(batchSize)
    print(" %d" % len(players))
    print("getting game analyses")
    analysesByPlayer = [(player, [ga for ga in self.env.gameAnalysisDB.byUserId(player.id) if len(ga.moveAnalyses) < 60]) for player in players]
    return analysesByPlayer

  def evaluate(self):
    print("evaluate model")
    print("getting model")
    model = self.gameModel()
    print("getting dataset")
    analysesByPlayer = self.getEvaluationDataset(self.config['evalSize'])
    activations = [Irwin.activation(self.predict([ga.moveAnalysisTensors() for ga in gameAnalyses[1]], model)) for gameAnalyses in analysesByPlayer]
    outcomes = list(zip(analysesByPlayer, [Irwin.outcome(a, 90, ap[0].engine) for ap, a in zip(analysesByPlayer, activations)]))
    tp = len([a for a in outcomes if a[1] == 1])
    fn = len([a for a in outcomes if a[1] == 2])
    tn = len([a for a in outcomes if a[1] == 3])
    fp = len([a for a in outcomes if a[1] == 4])

    fpnames = [a[0][0].id for a in outcomes if a[1] == 4]

    print("True positive: " + str(tp))
    print("False negative: " + str(fn))
    print("True negative: " + str(tn))
    print("False positive: " + str(fp))

    pprint(fpnames)

  @staticmethod
  def outcome(a, t, e): # activation, threshold, expected value
    if a > t and e:
      return 1 # true positive
    if a <= t and e:
      return 2 # false negative
    if a <= t and not e:
      return 3 # true negative
    else:
      return 4 # false positive

  def predict(self, tensors, model=None):
    if model == None:
      model = self.gameModel() 

    pvs =         [[m[0] for m in p] for p in tensors]
    moveStats =   [[m[1] for m in p] for p in tensors]
    moveNumbers = [[m[2] for m in p] for p in tensors]
    ranks =       [[m[3] for m in p] for p in tensors]
    advs =        [[m[4] for m in p] for p in tensors]

    predictions = [model.predict([np.array([p]), np.array([m]), np.array([mn]), np.array([r]), np.array([a])]) for p, m, mn, r, a in zip(pvs, moveStats, moveNumbers, ranks, advs)]
    return predictions

  def report(self, userId, gameAnalysisStore):
    predictions = self.predict(gameAnalysisStore.gameAnalysisTensors())
    report = {
      'userId': userId,
      'isLegit': True,
      'pv0ByAmbiguity': [0,0,0,0,0],
      'activation': Irwin.activation(predictions),
      'games': [Irwin.gameReport(ga, p) for ga, p in zip(gameAnalysisStore.gameAnalyses, list(predictions))]
    }
    return report

  @staticmethod
  def activation(predictions): # this is a weighted average. 90+ -> 10x, 80+ -> 5x, 70+ -> 3x, 60+ -> 2x, 50- -> 1x
    ps = []
    [ps.extend(Irwin.activationWeight(p[0])*[p[0]]) for p in predictions]
    if len(ps) == 0:
      return 0
    return int(100*sum(ps)/len(ps))

  @staticmethod
  def activationWeight(v):
    if v > 0.90:
      return 10
    if v > 0.80:
      return 5
    if v > 0.70:
      return 3
    if v > 0.60:
      return 2
    return 1

  @staticmethod
  def gameReport(gameAnalysis, prediction):
    return {
      'gameId': gameAnalysis.gameId,
      'activation': int(100*prediction[0]),
      'moves': [Irwin.moveReport(am, p) for am, p in zip(gameAnalysis.moveAnalyses, list(prediction[1][0]))]
    }

  @staticmethod
  def moveReport(analysedMove, prediction):
    return {
      'a': int(100*prediction[0]),
      'r': analysedMove.trueRank(),
      'm': analysedMove.ambiguity(),
      'o': int(100*analysedMove.advantage()),
      'l': int(100*analysedMove.winningChancesLoss())
    }

  @staticmethod
  def getGameEngineStatus(gameAnalysis, players):
    return any([p for p in players if gameAnalysis.userId == p.id and p.engine])

  @staticmethod
  def assignLabels(gameAnalyses, players):
    return [int(Irwin.getGameEngineStatus(gameAnalysis, players)) for gameAnalysis in gameAnalyses]

  @staticmethod
  def createBatchAndLabels(cheatBatch, legitBatch):
    batches = []
    # group the dataset into batches by the length of the dataset, because numpy needs it that way
    for x in range(22, 60):
      cheats = list([r for r in cheatBatch if len(r) == x])
      legits = list([r for r in legitBatch if len(r) == x])

      mlen = min(len(cheats), len(legits))

      cheats = cheats[:mlen]
      legits = legits[:mlen]

      cl = [True]*len(cheats) + [False]*len(legits)

      blz = list(zip(cheats+legits, cl))
      shuffle(blz)

      # only make the batch trainable if it's big
      if len(cheats + legits) > 64:
        pvs =         np.array([[m[0] for m in p[0]] for p in blz])
        moveStats =   np.array([[m[1] for m in p[0]] for p in blz])
        moveNumbers = np.array([[m[2] for m in p[0]] for p in blz])
        ranks =       np.array([[m[3] for m in p[0]] for p in blz])
        advs =        np.array([[m[4] for m in p[0]] for p in blz])

        b = [pvs, moveStats, moveNumbers, ranks, advs]
        l = [
          np.array([int(i[1]) for i in blz]), 
          np.array([[[int(i[1])]]*len(moveStats[0]) for i in blz])
        ]

        batches.append({
          'batch': b,
          'labels': l
        })
    shuffle(batches)
    return batches

  @staticmethod
  def flatten(l):
    return [item for sublist in l for item in sublist]
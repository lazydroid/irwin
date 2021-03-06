from default_imports import *

from modules.queue.Env import Env
from modules.queue.EngineQueue import EngineQueue, EngineQueueID
from modules.game.Player import PlayerID

from modules.auth.Auth import Authable

class Queue(NamedTuple('Queue', [('env', Env)])):
    def nextEngineAnalysis(self, id: EngineQueueID) -> Opt[EngineQueue]:
        return self.env.engineQueueDB.nextUnprocessed(id)

    def completeEngineAnalysis(self, _id: EngineQueueID):
        return self.env.engineQueueDB.updateComplete(_id, complete=True)

    def nextIrwinAnalysis(self):
        return None
        #return self.env.irwinAnalysisQueueDB.

    def queueNerualAnalysis(self, playerId: PlayerID):
        ...

    def queueEngineAnalysis(self, engineQueue: EngineQueue):
        return self.env.engineQueueDB.write(engineQueue)

    def engineQueueById(self, playerId: PlayerID):
        return self.env.engineQueueDB.byPlayerId(playerId)
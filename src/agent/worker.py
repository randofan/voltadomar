import logging
from asyncio import create_task

logger = logging.getLogger(__name__)


class Worker:
    '''
    Worker.
    '''

    def __init__(self, manager, worker_func):
        '''
        Initializes the Worker.
        '''
        self.manager = manager
        self.worker_func = worker_func

    async def _run_job(self, func):
        '''
        Runs the func with jobs from the input queue and
        puts the output on the output queue.
        '''
        while True:
            job = await self.manager.get_input()
            result = await func(job)
            await self.manager.add_output(result)

    def run(self):
        '''
        Starts the worker task.
        '''
        create_task(self._run_job(self.worker_func))

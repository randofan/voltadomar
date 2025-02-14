import logging
from asyncio import Queue

from agent.worker import Worker

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class WorkerManager:
    def __init__(self, worker_num, worker_func):
        self.input_queue = Queue()
        self.output_queue = Queue()
        self.worker_pool = {}
        for i in range(worker_num):
            self.worker_pool[i] = Worker(self, worker_func)
            logger.debug(f"Worker {i} created")

    def run_jobs(self):
        for i, worker in self.worker_pool.items():
            worker.run()
            logger.debug(f"Worker {i} task started.")

    async def add_input(self, job):
        await self.input_queue.put(job)
        logger.debug(f"Job added to input queue: {job}")

    async def get_input(self):
        job = await self.input_queue.get()
        self.input_queue.task_done()
        logger.debug(f"Job retrieved from input queue: {job}")
        return job

    async def add_output(self, result):
        await self.output_queue.put(result)
        logger.debug(f"Result added to output queue: {result}")

    async def get_output(self):
        result = await self.output_queue.get()
        self.output_queue.task_done()
        logger.debug(f"Result retrieved from output queue: {result}")
        return result

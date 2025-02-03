import logging
from asyncio import Queue, create_task

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class WorkerManager:
    def __init__(self, worker_num, worker_func):
        self.input_queue = Queue()
        self.output_queue = Queue()
        self.worker_pool = {}
        for i in range(worker_num):
            # TODO create Worker class and move create_task() into a run() inside
            self.worker_pool[i] = create_task(self.run_job(worker_func))
            logger.debug(f"Worker {i} created and task started.")

    async def add_input(self, job):
        await self.input_queue.put(job)
        logger.debug(f"Job added to input queue: {job}")

    async def add_output(self, result):
        await self.output_queue.put(result)
        logger.debug(f"Result added to output queue: {result}")

    async def run_job(self, func):
        while True:
            job = await self.input_queue.get()
            logger.debug(f"Job retrieved from input queue: {job}")
            try:
                result = await func(job)
                await self.output_queue.put(result)
                logger.debug(f"Job processed and result added to output queue: {result}")
            except Exception as e:
                logger.error(f"Error processing job {job}: {e}")
            finally:
                self.input_queue.task_done()
                logger.debug(f"Job marked as done: {job}")

    async def get_output(self):
        result = await self.output_queue.get()
        self.output_queue.task_done()
        logger.debug(f"Result retrieved from output queue: {result}")
        return result

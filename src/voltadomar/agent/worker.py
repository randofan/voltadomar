"""
agent/worker.py

WorkerManager class for managing a pool of workers. Each worker
is a asynchronous task that processes jobs from an input queue and
puts results into an output queue. The WorkerManager handles
starting, stopping, and cancelling the workers.

Author: David Song <davsong@cs.washington.edu>
"""

import logging
import asyncio
from typing import Any, Awaitable, Callable, List, Optional

logger = logging.getLogger(__name__)

JobProcessor = Callable[[Any], Awaitable[Any]]


class WorkerManager:
    """Manages a pool of asynchronous workers processing jobs from queues."""
    def __init__(self, worker_num: int, job_processor: JobProcessor):
        """
        Initializes the WorkerManager.

        Args:
            worker_num: The number of worker tasks to create.
            job_processor: The asynchronous function each worker will execute.
        """
        if worker_num <= 0:
            raise ValueError("Number of workers must be positive.")
        self.worker_num = worker_num
        self.job_processor = job_processor
        self.input_queue: asyncio.Queue[Any] = asyncio.Queue()
        self.output_queue: asyncio.Queue[Any] = asyncio.Queue()
        self._tasks: List[asyncio.Task[None]] = []

    async def _worker_loop(self):
        """The main loop for a single worker task."""
        while True:
            job = await self.get_input()
            if job is None:  # Sentinel value to stop the worker
                logger.debug("Worker received None, stopping.")
                break
            try:
                result = await self.job_processor(job)
                await self.add_output(result)
            except Exception as e:
                logger.exception(f"Error processing job: {job} with error:\n{e}")
                await self.add_output(None)  # Add None to output on error

    def start(self):
        """Starts the worker tasks."""
        if self._tasks:
            logger.warning("Workers already started.")
            return

        self._tasks = [
            asyncio.create_task(self._worker_loop(), name=f"Worker-{i}")
            for i in range(self.worker_num)
        ]
        logger.info(f"Started {self.worker_num} worker tasks.")

    async def add_input(self, job: Any):
        """Adds a job to the input queue."""
        await self.input_queue.put(job)
        logger.debug(f"Job added to input queue: {job}")

    async def get_input(self) -> Optional[Any]:
        """Retrieves a job from the input queue."""
        job = await self.input_queue.get()
        self.input_queue.task_done()
        logger.debug(f"Job retrieved from input queue: {job}")
        return job

    async def add_output(self, result: Any):
        """Adds a result to the output queue."""
        await self.output_queue.put(result)
        logger.debug(f"Result added to output queue: {result}")

    async def get_output(self) -> Any:
        """Retrieves a result from the output queue."""
        result = await self.output_queue.get()
        self.output_queue.task_done()
        logger.debug(f"Result retrieved from output queue: {result}")
        return result

    async def join(self):
        """
        Waits for all jobs in the input queue to be processed and
        all results in the output queue to be retrieved.
        """
        logger.info("Waiting for input queue to be processed...")
        await self.input_queue.join()
        logger.info("Input queue processed. Waiting for output queue...")
        await self.output_queue.join()
        logger.info("Output queue processed.")

    async def stop(self):
        """
        Signals workers to stop after processing remaining jobs
        and waits for them to finish.
        """
        logger.info("Signaling workers to stop...")
        for _ in range(self.worker_num):
            await self.add_input(None)  # Send sentinel value

        if self._tasks:
            logger.info("Waiting for worker tasks to complete...")
            await asyncio.gather(*self._tasks, return_exceptions=True)
            logger.info("All worker tasks finished.")
            self._tasks = []
        else:
            logger.warning("No worker tasks are currently running.")

    async def cancel(self):
        """Cancels all running worker tasks immediately."""
        if not self._tasks:
            logger.warning("No worker tasks to cancel.")
            return

        logger.info(f"Cancelling {len(self._tasks)} worker tasks...")
        for task in self._tasks:
            if not task.done():
                task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)
        logger.info("Worker tasks cancellation complete.")
        self._tasks = []

        while not self.input_queue.empty():
            self.input_queue.get_nowait()
            self.input_queue.task_done()
        while not self.output_queue.empty():
            self.output_queue.get_nowait()
            self.output_queue.task_done()
        logger.info("Input and output queues cleared after cancellation.")

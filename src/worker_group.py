from asyncio import Queue, create_task, gather, get_event_loop


class WorkerGroup:
    def __init__(self, worker_num, worker_func):
        self.input_queue = Queue()
        self.output_queue = Queue()
        self.worker_manager = {}
        for i in range(worker_num):
            self.worker_manager[i] = create_task(self.run_job(worker_func))

    def __del__(self):
        for worker in self.worker_manager.values():
            worker.cancel()
        get_event_loop().run_until_complete(
            lambda self: gather(*self.worker_manager.values(), return_exceptions=True))

    async def add_input(self, job):
        await self.input_queue.put(job)

    async def add_output(self, result):
        await self.output_queue.put(result)

    async def run_job(self, func):
        while True:
            job = await self.input_queue.get()
            result = await func(job)
            await self.output_queue.put(result)
            self.input_queue.task_done()

    async def get_output(self):
        result = await self.output_queue.get()
        self.output_queue.task_done()
        return result

import asyncio
import time
import inspect
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from app.capture_engine.source import EndOfSource, VideoSource

from .frame_queue import FrameQueue
from .metrics import PipelineMetrics
from .processor import FrameProcessor, ProcessedFrame


class FramePipeline:
    def __init__(self, source: VideoSource, processor: FrameProcessor,
                 publish: Callable[[ProcessedFrame], None], capacity: int = 2):
        self.source = source
        self.processor = processor
        self.publish = publish
        self.queue = FrameQueue(capacity)
        self.metrics = PipelineMetrics()
        self._stop = asyncio.Event()
        self.eof = False

    def request_stop(self) -> None:
        self._stop.set()
        self.queue.close(discard=True)

    def snapshot(self) -> dict:
        return self.metrics.snapshot(self.queue)

    async def run(self) -> None:
        # Distinct executors ensure processing cannot occupy the capture worker.
        capture_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="zeros-capture")
        process_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="zeros-process")
        self.metrics.active = True
        producer = asyncio.create_task(self._capture(capture_worker))
        consumer = asyncio.create_task(self._process(process_worker))
        try:
            await asyncio.gather(producer, consumer)
        finally:
            self.request_stop()
            # Never cancel a running native decoder/inference call and release
            # its resources underneath it. Explicit stop waits for both tasks.
            await asyncio.gather(producer, consumer, return_exceptions=True)
            capture_worker.shutdown(wait=True)
            process_worker.shutdown(wait=True)
            self.metrics.active = False

    async def _capture(self, executor: ThreadPoolExecutor) -> None:
        loop = asyncio.get_running_loop()
        try:
            while not self._stop.is_set():
                tick = time.monotonic()
                frame = await loop.run_in_executor(executor, self.source.get_frame)
                if frame is not None and not self._stop.is_set():
                    self.metrics.record_capture()
                    self.queue.offer(frame)
                del frame
                remaining = max(0.001, 1 / self.source.capture_fps - (time.monotonic() - tick))
                try:
                    await asyncio.wait_for(self._stop.wait(), remaining)
                except TimeoutError:
                    pass
        except EndOfSource:
            self.eof = True
        finally:
            # EOF drains the newest pending frame; explicit stop/failure drops it.
            self.queue.close(discard=self._stop.is_set())

    async def _process(self, executor: ThreadPoolExecutor) -> None:
        loop = asyncio.get_running_loop()
        while (frame := await self.queue.take_latest()) is not None:
            if self._stop.is_set():
                self.metrics.discarded_in_flight += 1
                return
            self.metrics.in_flight = 1
            started = time.monotonic()
            try:
                result = await loop.run_in_executor(executor, self.processor.process, frame)
                if self._stop.is_set():
                    self.metrics.discarded_in_flight += 1
                else:
                    published = self.publish(result)
                    if inspect.isawaitable(published):
                        await published
                    self.metrics.record_processed(frame.captured_at, started, time.monotonic())
                del result
            except Exception:
                self.metrics.failed_frames += 1
                raise
            finally:
                self.metrics.in_flight = 0
            del frame

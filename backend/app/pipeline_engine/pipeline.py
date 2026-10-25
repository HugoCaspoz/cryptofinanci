import asyncio
import time
import inspect
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from app.capture_engine.source import EndOfSource, VideoSource

from .temporal_buffer import TemporalBuffer
from .sampling import SmartSampler
from .frame_queue import FrameQueue
from .metrics import PipelineMetrics
from .processor import FrameProcessor, ProcessedFrame


class FramePipeline:
    def __init__(self, source: VideoSource, processor: FrameProcessor,
                 publish: Callable[[ProcessedFrame], None], capacity: int = 2, on_processed=None, buffer_seconds=10, on_error=None):
        self.source = source
        self.processor = processor
        self.publish = publish
        self.on_processed = on_processed
        self.on_error = on_error
        self.queue = FrameQueue(capacity)
        self.buffer = TemporalBuffer(buffer_seconds)
        self.metrics = PipelineMetrics()
        self._stop = asyncio.Event()
        self.eof = False
        self.paused = False
        self._running = asyncio.Event()
        self._running.set()
        self._capture_guard = asyncio.Lock()
        self._process_guard = asyncio.Lock()
        layout = getattr(getattr(processor, "vision", None), "layout", None)
        self.sampler = SmartSampler(layout) if source.sampling_mode == "adaptive" else None

    def request_stop(self) -> None:
        self._stop.set()
        self._running.set()
        self.queue.close(discard=True)

    async def pause(self):
        self.paused = True
        self._running.clear()
        async with self._capture_guard:
            if hasattr(self.source, "pause"):
                self.source.pause()
        async with self._process_guard:
            pass  # A native call and its publication must finish before editing.

    def resume(self):
        if hasattr(self.source, "resume"):
            self.source.resume()
        self.paused = False
        self._running.set()

    def snapshot(self) -> dict:
        result = self.metrics.snapshot(self.queue)
        result["buffer"] = self.buffer.snapshot()
        result["sampling"] = self.sampler.snapshot() if self.sampler else {"mode": "fixed", "target_fps": self.source.capture_fps}
        return result

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

    def _sample_frame(self):
        frame = self.source.get_frame()
        if frame is not None:
            self.buffer.append(frame)
        return frame if frame is None or self.sampler is None or self.sampler.select(frame) else None

    async def _capture(self, executor: ThreadPoolExecutor) -> None:
        loop = asyncio.get_running_loop()
        try:
            while not self._stop.is_set():
                tick = time.monotonic()
                await self._running.wait()
                if self._stop.is_set():
                    break
                async with self._capture_guard:
                    if self.paused:
                        continue
                    frame = await loop.run_in_executor(executor, self._sample_frame)
                    if frame is not None and not self._stop.is_set():
                        capture_ms = frame.capture_latency_ms
                        if capture_ms is None:
                            capture_ms = (time.monotonic() - tick) * 1000
                        self.metrics.record_origin(frame.frame_id, frame.captured_at, capture_ms)
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
            self.metrics.in_flight = 1
            try:
                while True:
                    await self._running.wait()
                    async with self._process_guard:
                        if self.paused and not self._stop.is_set():
                            continue
                        await self._process_one(frame, executor, loop)
                        break
            finally:
                self.metrics.in_flight = 0
            del frame

    async def _process_one(self, frame, executor, loop):
        if self._stop.is_set():
            self.metrics.discarded_in_flight += 1
            return
        started = time.monotonic()
        stage = "vision"
        try:
            result = await loop.run_in_executor(executor, self.processor.process, frame)
            stage = "publish"
            if self._stop.is_set():
                self.metrics.discarded_in_flight += 1
            else:
                publish_started = time.monotonic()
                published = self.publish(result)
                if inspect.isawaitable(published):
                    published = await published
                finished = time.monotonic()
                for name, duration in result.timings.items():
                    if name in {"vision", "preview"}:
                        self.metrics.latencies[name].add(duration, frame.frame_id)
                if isinstance(published, dict) and "state" in published:
                    self.metrics.latencies["state"].add(published["state"], frame.frame_id)
                self.metrics.latencies["publish"].add((finished - publish_started) * 1000, frame.frame_id)
                origin = self.metrics.origins.get(frame.frame_id)
                if origin is not None:
                    self.metrics.latencies["total_backend"].add((finished - origin) * 1000, frame.frame_id)
                self.metrics.in_flight = 0
                self.metrics.record_processed(frame.captured_at, started, finished)
                if self.on_processed:
                    self.on_processed()
            del result
        except Exception as exc:
            self.metrics.failed_frames += 1
            if self.on_error:
                try:
                    await self.on_error(frame, stage, type(exc).__name__)
                except Exception:
                    pass  # Preserve the original pipeline failure and pending archive.
            raise
        finally:
            self.metrics.in_flight = 0

"""Latest committed capture snapshot, with one pending item per subscriber."""
import asyncio


class CaptureHub:
    def __init__(self):
        self.latest = None
        self.subscribers = set()

    def publish(self, snapshot):
        self.latest = snapshot
        for queue in self.subscribers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(snapshot)

    def subscribe(self):
        queue = asyncio.Queue(maxsize=1)
        self.subscribers.add(queue)
        if self.latest is not None:
            queue.put_nowait(self.latest)
        return queue

    def unsubscribe(self, queue):
        self.subscribers.discard(queue)

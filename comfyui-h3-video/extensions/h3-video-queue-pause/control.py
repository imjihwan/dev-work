"""Hold the next dequeue without touching running work or queued payloads."""
import json
import os
from pathlib import Path
import time


class QueuePauseGate:
    def __init__(self, queue, state_path):
        self.queue=queue;self.condition=queue.not_empty;self.original_get=queue.get
        self.path=Path(state_path);self.storage_error=False
        try:
            value=json.loads(self.path.read_text(encoding='utf-8'))
            if type(value.get('paused')) is not bool:raise ValueError('Invalid pause state')
            self.paused=value['paused']
        except FileNotFoundError:self.paused=False
        except (OSError,ValueError,AttributeError):self.paused=True;self.storage_error=True

    def install(self):
        self.queue.get=self.get
        return self

    def snapshot(self):
        with self.condition:
            running=len(self.queue.currently_running)
            return dict(supported=True,paused=self.paused,
                        state=('finishing' if running else 'paused') if self.paused else 'running',
                        running=running,pending=len(self.queue.queue),storage_error=self.storage_error)

    def set_paused(self, paused):
        if type(paused) is not bool:raise ValueError('Pause state must be boolean')
        with self.condition:
            temporary=self.path.with_name(self.path.name+'.writing')
            temporary.write_text(json.dumps({'paused':paused}),encoding='utf-8')
            os.replace(temporary,self.path)
            self.paused=paused;self.storage_error=False
            self.condition.notify_all()
            return self.snapshot()

    def get(self, timeout=None):
        deadline=None if timeout is None else time.monotonic()+timeout
        with self.condition:
            while self.paused or not self.queue.queue:
                remaining=None if deadline is None else deadline-time.monotonic()
                if remaining is not None and remaining<=0:return None
                self.condition.wait(timeout=remaining)
            # Check and dequeue under the same native lock as set_paused.
            # Never enter the native empty-queue wait, which cannot see our flag.
            return self.original_get(timeout=0)

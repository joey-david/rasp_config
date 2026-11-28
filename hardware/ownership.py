"""Tie wheel writes and worker cleanup to the action that acquired the robot."""

from contextvars import ContextVar
from functools import wraps
import threading


class MotionOwner:
    def __init__(self):
        self.lock = threading.RLock()
        self.context = ContextVar("motion_owner", default=None)
        self.active = None
        self.name = None
        self.workers = 0

    def claim(self, name):
        with self.lock:
            if self.active is not None:
                return None
            self.active = object()
            self.name = name
            self.workers = 1
            return self.active

    def release(self, token):
        with self.lock:
            if token is self.active and token is not None:
                self.workers -= 1
                if self.workers == 0:
                    self.revoke()

    def revoke(self):
        with self.lock:
            self.active = self.name = None
            self.workers = 0

    def run(self, token, call):
        previous = self.context.set(token)
        try:
            with self.lock:
                if token is not self.active:
                    return {"ok": False, "error": "action cancelled"}
            return call()
        finally:
            self.context.reset(previous)
            self.release(token)

    def thread(self, target, *, name):
        token = self.context.get()
        with self.lock:
            if token is None:
                token = self.claim(name)
                if token is None:
                    raise RuntimeError("motion busy")
            elif token is self.active:
                self.workers += 1
            else:
                raise RuntimeError("action cancelled")
        worker = threading.Thread(target=self.run, args=(token, target), daemon=True, name=name)
        try:
            worker.start()
        except BaseException:
            self.release(token)
            raise
        return worker


def owned_write(method):
    @wraps(method)
    def write(robot, *args, **kwargs):
        owner = robot.owner
        with owner.lock:
            if owner.context.get() is not owner.active:
                return {"ok": False, "veto": "motion owner changed"}
            return method(robot, *args, **kwargs)
    return write

"""
A threaded task wrapper.

This module implements a single class: `Future`, quite similar to
`concurrent.futures.Future`
(https://docs.python.org/3/library/concurrent.futures.html#future-objects).

Unlike the official library version, the thread is always daemon to allow
smooth shutdowns.

Callbacks are also implemented differently: a callback is always called by the
task thread immediately after completion of the target function.

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
import threading


class Future:
    """
    Thread wrapper that provides the "result" like concurrent.futures.

    `concurrent.futures` does not kill the threads with atexit, making processes hang.

    A callback method can be provided to manage exceptions or process the result.
    """

    def __init__(self, target, args=(), kwargs=None, callback=None):
        """
        Run function "target" on a separate thread, with provided arg and kwargs.
        If callback is not None, call callback after completion of target or
        if an exception in raised.

        Parameters:
            target (callable): the function or method to run on a thread
            args (tuple): args to pass to the target method
            kwargs (bool): kwargs to pass to the target method
            callback (callable): a function of the form f(result, error) called
            when the task completes (in error or not)
        """
        self._target = target
        self._done = False
        self._result = None
        self._error = None
        self._callback = callback
        kwargs = kwargs or {}
        self._thread = threading.Thread(
            target=self._run, args=args, kwargs=kwargs, daemon=True
        )
        self._thread.start()

    def _run(self, *args, **kwargs):
        """
        Run the target function on a separate thread.
        """
        try:
            self._result = self._target(*args, **kwargs)
        except BaseException as error:
            # Catch any error
            self._error = error
        if self._callback is not None:
            # Callback with result and/or error
            self._callback(self._result, self._error)
            self._done = True
        elif self._error is not None:
            raise self._error
        self._done = True

    def exception(self, timeout=None):
        """
        Return exception if the task ended in error. If the task is not completed yet,
        wait up to timeout seconds. Raise TimeoutError if the call hasn’t completed in
        timeout seconds. Wait forever if timeout is None (default).

        If the task completed without raising, None is returned.
        """
        if not self.done():
            self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            raise TimeoutError
        return self._error

    def done(self):
        """
        True if the task has completed (in error or not)
        """
        return self._done

    def result(self, timeout=None):
        """
        Return result of the task. If the task is not completed yet,
        wait up to timeout seconds. Raise TimeoutError if the task hasn’t completed in
        timeout seconds. Wait forever if timeout is None (default).
        """
        if not self.done():
            self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            raise TimeoutError
        return self._result

    def join(self, timeout=None):
        """
        Join the thread (see threading.Thread.join)
        """
        self._thread.join(timeout=timeout)

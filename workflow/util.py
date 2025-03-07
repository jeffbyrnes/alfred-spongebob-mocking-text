#!/usr/bin/env python3

"""A selection of helper functions useful for building workflows."""

import atexit
import errno
import fcntl
import functools
import json
import os
import signal
import subprocess
import sys
import time
from collections import namedtuple
from contextlib import contextmanager
from threading import Event


# JXA scripts to call Alfred's API via the Scripting Bridge
# {app} is automatically replaced with "Alfred 3" or
# "com.runningwithcrayons.Alfred" depending on version.
#
# Open Alfred in search (regular) mode
JXA_SEARCH = "Application({app}).search({arg});"
# Open Alfred's File Actions on an argument
JXA_ACTION = "Application({app}).action({arg});"
# Open Alfred's navigation mode at path
JXA_BROWSE = "Application({app}).browse({arg});"
# Set the specified theme
JXA_SET_THEME = "Application({app}).setTheme({arg});"
# Call an External Trigger
JXA_TRIGGER = "Application({app}).runTrigger({arg}, {opts});"
# Save a variable to the workflow configuration sheet/info.plist
JXA_SET_CONFIG = "Application({app}).setConfiguration({arg}, {opts});"
# Delete a variable from the workflow configuration sheet/info.plist
JXA_UNSET_CONFIG = "Application({app}).removeConfiguration({arg}, {opts});"
# Tell Alfred to reload a workflow from disk
JXA_RELOAD_WORKFLOW = "Application({app}).reloadWorkflow({arg});"


class AcquisitionError(Exception):
    """Raised if a lock cannot be acquired."""


AppInfo = namedtuple("AppInfo", ["name", "path", "bundleid"])
"""Information about an installed application.

Returned by :func:`appinfo`.

.. py:attribute:: name

    Name of the application, e.g. ``'Safari'``.

.. py:attribute:: path

    Path to the application bundle, e.g. ``'/Applications/Safari.app'``.

.. py:attribute:: bundleid

    Application's bundle ID, e.g. ``'com.apple.Safari'``.

"""


def applescriptify(string):
    """Escape string for insertion into an AppleScript string.

    Replaces ``"`` with `"& quote &"`. Use this function if you want
    to insert a string into an AppleScript script:

        >>> applescriptify('g "python" test')
        'g " & quote & "python" & quote & "test'

    Args:
        s (str): String to escape.

    Returns:
        str: Escaped string.

    """
    return string.replace('"', '" & quote & "')


def run_command(cmd, **kwargs):
    """Run a command and return the output.

    .. versionadded:: 1.31

    A thin wrapper around :func:`subprocess.check_output` that ensures
    all arguments are encoded to UTF-8 first.

    Args:
        cmd (list): Command arguments to pass to :func:`~subprocess.check_output`.
        **kwargs: Keyword arguments to pass to :func:`~subprocess.check_output`.

    Returns:
        str: Output returned by :func:`~subprocess.check_output`.

    """
    cmd = [str(s) for s in cmd]
    return subprocess.check_output(cmd, **kwargs).decode()


def run_applescript(script, *args, **kwargs):
    """Execute an AppleScript script and return its output.

    Run AppleScript either by filepath or code. If ``script`` is a valid
    filepath, that script will be run, otherwise ``script`` is treated
    as code.

    Args:
        script (str, optional): Filepath of script or code to run.
        *args: Optional command-line arguments to pass to the script.
        **kwargs: Pass ``lang`` to run a language other than AppleScript.
            Any other keyword arguments are passed to :func:`~subprocess.run`.

    Returns:
        str: Output of run command.

    """
    lang = "AppleScript"

    if "lang" in kwargs:
        lang = kwargs["lang"]
        del kwargs["lang"]

    cmd = ["/usr/bin/osascript", "-l", lang]

    if os.path.exists(script):
        cmd += [script]
    else:
        cmd += ["-e", script]

    cmd.extend(args)

    return run_command(cmd, **kwargs)


def run_jxa(script, *args):
    """Execute a JXA script and return its output.

    Wrapper around :func:`run_applescript` that passes ``lang=JavaScript``.

    Args:
        script (str): Filepath of script or code to run.
        *args: Optional command-line arguments to pass to script.

    Returns:
        str: Output of script.

    """
    return run_applescript(script, *args, lang="JavaScript")


def run_trigger(name, bundleid=None, arg=None):
    """Call an Alfred External Trigger.

    If ``bundleid`` is not specified, the bundle ID of the calling
    workflow is used.

    Args:
        name (str): Name of External Trigger to call.
        bundleid (str, optional): Bundle ID of workflow trigger belongs to.
        arg (str, optional): Argument to pass to trigger.

    """
    bundleid = bundleid or os.getenv("alfred_workflow_bundleid")
    appname = "com.runningwithcrayons.Alfred"
    opts = {"inWorkflow": bundleid}

    if arg:
        opts["withArgument"] = arg

    script = JXA_TRIGGER.format(
        app=json.dumps(appname),
        arg=json.dumps(name),
        opts=json.dumps(opts, sort_keys=True),
    )
    run_applescript(script, lang="JavaScript")


def set_theme(theme_name):
    """Change Alfred's theme.

    Args:
        theme_name (str): Name of theme Alfred should use.

    """
    appname = "com.runningwithcrayons.Alfred"
    script = JXA_SET_THEME.format(app=json.dumps(appname), arg=json.dumps(theme_name))
    run_applescript(script, lang="JavaScript")


def set_config(name, value, bundleid=None, exportable=False):
    """Set a workflow variable in ``info.plist``.

    If ``bundleid`` is not specified, the bundle ID of the calling
    workflow is used.

    Args:
        name (str): Name of variable to set.
        value (str): Value to set variable to.
        bundleid (str, optional): Bundle ID of workflow variable belongs to.
        exportable (bool, optional): Whether variable should be marked
            as exportable (Don't Export checkbox).

    """
    bundleid = bundleid or os.getenv("alfred_workflow_bundleid")
    appname = "com.runningwithcrayons.Alfred"
    opts = {
        "toValue": value,
        "inWorkflow": bundleid,
        "exportable": exportable,
    }
    script = JXA_SET_CONFIG.format(
        app=json.dumps(appname),
        arg=json.dumps(name),
        opts=json.dumps(opts, sort_keys=True),
    )
    run_applescript(script, lang="JavaScript")


def unset_config(name, bundleid=None):
    """Delete a workflow variable from ``info.plist``.

    If ``bundleid`` is not specified, the bundle ID of the calling
    workflow is used.

    Args:
        name (str): Name of variable to delete.
        bundleid (str, optional): Bundle ID of workflow variable belongs to.

    """
    bundleid = bundleid or os.getenv("alfred_workflow_bundleid")
    appname = "com.runningwithcrayons.Alfred"
    opts = {"inWorkflow": bundleid}
    script = JXA_UNSET_CONFIG.format(
        app=json.dumps(appname),
        arg=json.dumps(name),
        opts=json.dumps(opts, sort_keys=True),
    )
    run_applescript(script, lang="JavaScript")


def search_in_alfred(query=None):
    """Open Alfred with given search query.

    Omit ``query`` to simply open Alfred's main window.

    Args:
        query (str, optional): Search query.

    """
    query = query or ""
    appname = "com.runningwithcrayons.Alfred"
    script = JXA_SEARCH.format(app=json.dumps(appname), arg=json.dumps(query))
    run_applescript(script, lang="JavaScript")


def browse_in_alfred(path):
    """Open Alfred's filesystem navigation mode at ``path``.

    Args:
        path (str): File or directory path.

    """
    appname = "com.runningwithcrayons.Alfred"
    script = JXA_BROWSE.format(app=json.dumps(appname), arg=json.dumps(path))
    run_applescript(script, lang="JavaScript")


def action_in_alfred(paths):
    """Action the give filepaths in Alfred.

    Args:
        paths (list): Paths to files/directories to action.

    """
    appname = "com.runningwithcrayons.Alfred"
    script = JXA_ACTION.format(app=json.dumps(appname), arg=json.dumps(paths))
    run_applescript(script, lang="JavaScript")


def reload_workflow(bundleid=None):
    """Tell Alfred to reload a workflow from disk.

    If ``bundleid`` is not specified, the bundle ID of the calling
    workflow is used.

    Args:
        bundleid (str, optional): Bundle ID of workflow to reload.

    """
    bundleid = bundleid or os.getenv("alfred_workflow_bundleid")
    appname = "com.runningwithcrayons.Alfred"
    script = JXA_RELOAD_WORKFLOW.format(
        app=json.dumps(appname), arg=json.dumps(bundleid)
    )
    run_applescript(script, lang="JavaScript")


def appinfo(name):
    """Get information about an installed application.

    Args:
        name (str): Name of application to look up.

    Returns:
        AppInfo: :class:`AppInfo` tuple or ``None`` if app isn't found.

    """
    cmd = [
        "mdfind",
        "-onlyin",
        "/Applications",
        "-onlyin",
        "/System/Applications",
        "-onlyin",
        os.path.expanduser("~/Applications"),
        "(kMDItemContentTypeTree == com.apple.application &&"
        f'(kMDItemDisplayName == "{name}" || kMDItemFSName == "{name}.app"))',
    ]

    output = run_command(cmd).strip()

    if not output:
        return None

    path = output.split("\n", maxsplit=1)[0]
    cmd = ["mdls", "-raw", "-name", "kMDItemCFBundleIdentifier", path]
    bid = run_command(cmd).strip()

    if not bid:  # pragma: no cover
        return None

    return AppInfo(name, path, bid)


@contextmanager
def atomic_writer(fpath, mode):
    """Atomic file writer.

    Context manager that ensures the file is only written if the write
    succeeds. The data is first written to a temporary file.

    :param fpath: path of file to write to.
    :type fpath: ``str``
    :param mode: sames as for :func:`open`
    :type mode: string

    """
    suffix = f".{os.getpid()}.tmp"
    temppath = fpath + suffix
    with open(temppath, mode) as f:  # pylint: disable=unspecified-encoding
        try:
            yield f
            os.rename(temppath, fpath)
        finally:
            try:
                os.remove(temppath)
            except (OSError, IOError):
                pass


class LockFile:
    """Context manager to protect filepaths with lockfiles.

    Creates a lockfile alongside ``protected_path``. Other ``LockFile``
    instances will refuse to lock the same path.

    >>> path = '/path/to/file'
    >>> with LockFile(path):
    >>>     with open(path, 'wb') as f:
    >>>         f.write(data)

    Args:
        protected_path (str): File to protect with a lockfile
        timeout (float, optional): Raises an :class:`AcquisitionError`
            if lock cannot be acquired within this number of seconds.
            If ``timeout`` is 0 (the default), wait forever.
        delay (float, optional): How often to check (in seconds) if
            lock has been released.

    Attributes:
        delay (float): How often to check (in seconds) whether the lock
            can be acquired.
        lockfile (str): Path of the lockfile.
        timeout (float): How long to wait to acquire the lock.

    """

    def __init__(self, protected_path, timeout=0.0, delay=0.05):
        """Create new :class:`LockFile` object."""
        self.lockfile = protected_path + ".lock"
        self._lockfile = None
        self.timeout = timeout
        self.delay = delay
        self._lock = Event()
        atexit.register(self.release)

    @property
    def locked(self):
        """``True`` if file is locked by this instance."""
        return self._lock.is_set()

    def acquire(self, blocking=True):
        """Acquire the lock if possible.

        If the lock is in use and ``blocking`` is ``False``, return
        ``False``.

        Otherwise, check every :attr:`delay` seconds until it acquires
        lock or exceeds attr:`timeout` and raises an :class:`AcquisitionError`.

        """
        if self.locked and not blocking:
            return False

        start = time.time()
        while True:
            # Raise error if we've been waiting too long to acquire the lock
            if self.timeout and (time.time() - start) >= self.timeout:
                raise AcquisitionError("lock acquisition timed out")

            # If already locked, wait then try again
            if self.locked:
                time.sleep(self.delay)
                continue

            # Create in append mode so we don't lose any contents
            if self._lockfile is None:
                self._lockfile = open(
                    self.lockfile, "a", encoding="utf-8"
                )  # pylint: disable=consider-using-with

            # Try to acquire the lock
            try:
                fcntl.lockf(self._lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._lock.set()
                break
            except IOError as err:  # pragma: no cover
                if err.errno not in (errno.EACCES, errno.EAGAIN):
                    raise

                # Don't try again
                if not blocking:  # pragma: no cover
                    return False

                # Wait, then try again
                time.sleep(self.delay)

        return True

    def release(self):
        """Release the lock by deleting `self.lockfile`."""
        if not self._lock.is_set():
            return False

        try:
            fcntl.lockf(self._lockfile, fcntl.LOCK_UN)
        except IOError:  # pragma: no cover
            pass
        finally:
            self._lock.clear()
            self._lockfile = None
            try:
                os.unlink(self.lockfile)
            except (IOError, OSError):  # pragma: no cover
                pass

            return True  # pylint: disable=lost-exception

    def __enter__(self):
        """Acquire lock."""
        self.acquire()
        return self

    def __exit__(self, typ, value, traceback):
        """Release lock."""
        self.release()

    def __del__(self):
        """Clear up `self.lockfile`."""
        self.release()  # pragma: no cover


class uninterruptible:  # pylint: disable=invalid-name
    """Decorator that postpones SIGTERM until wrapped function returns.

    .. important:: This decorator is NOT thread-safe.

    As of version 2.7, Alfred allows Script Filters to be killed. If
    your workflow is killed in the middle of critical code (e.g.
    writing data to disk), this may corrupt your workflow's data.

    Use this decorator to wrap critical functions that *must* complete.
    If the script is killed while a wrapped function is executing,
    the SIGTERM will be caught and handled after your function has
    finished executing.

    Alfred-Workflow uses this internally to ensure its settings, data
    and cache writes complete.

    """

    def __init__(self, func, class_name=""):
        """Decorate `func`."""
        self.func = func
        functools.update_wrapper(self, func)
        self.class_name = class_name
        self._caught_signal = None
        self.old_signal_handler = signal.getsignal(signal.SIGTERM)

    def signal_handler(self, signum, frame):
        """Called when process receives SIGTERM."""
        self._caught_signal = (signum, frame)

    def __call__(self, *args, **kwargs):
        """Trap ``SIGTERM`` and call wrapped function."""
        self._caught_signal = None
        # Register handler for SIGTERM, then call `self.func`
        self.old_signal_handler = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, self.signal_handler)
        self.func(*args, **kwargs)

        # Restore old signal handler
        signal.signal(signal.SIGTERM, self.old_signal_handler)

        # Handle any signal caught during execution
        if self._caught_signal is not None:
            signum, frame = self._caught_signal

            if callable(self.old_signal_handler):
                self.old_signal_handler(signum, frame)
            elif self.old_signal_handler == signal.SIG_DFL:
                sys.exit(0)

    def __get__(self, obj=None, class_name=None):
        """Decorator API."""
        return self.__class__(self.func.__get__(obj, class_name), class_name.__name__)

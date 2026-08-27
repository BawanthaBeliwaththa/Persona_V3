"""
Cross-Platform Asynchronous Execution Bridge for Playwright
===========================================================
Guarantees a Windows ProactorEventLoop in a dedicated background thread
so that Playwright subprocesses (Chromium) run flawlessly on Windows without
colliding with Uvicorn's WindowsSelectorEventLoopPolicy.

Includes centralized serialization lock to ensure scraper operations execute
strictly one after another ("one scraped after one") without browser collisions.
"""

import asyncio
import sys
import threading
from typing import Any, Coroutine, Optional

_scraper_loop: Optional[asyncio.AbstractEventLoop] = None
_scraper_thread: Optional[threading.Thread] = None
_scraper_async_lock: Optional[asyncio.Lock] = None
_lock = threading.Lock()


def get_scraper_loop() -> asyncio.AbstractEventLoop:
    global _scraper_loop, _scraper_thread, _scraper_async_lock
    with _lock:
        if _scraper_loop is None or _scraper_loop.is_closed():
            if sys.platform == "win32":
                _scraper_loop = asyncio.ProactorEventLoop()
            else:
                _scraper_loop = asyncio.new_event_loop()
            
            def _runner():
                asyncio.set_event_loop(_scraper_loop)
                _scraper_loop.run_forever()

            _scraper_thread = threading.Thread(
                target=_runner,
                daemon=True,
                name="playwright-proactor-loop"
            )
            _scraper_thread.start()
            _scraper_async_lock = None
        return _scraper_loop


def get_scraper_lock() -> asyncio.Lock:
    """Return the global async lock that runs on the scraper loop to serialize browser access."""
    global _scraper_async_lock
    loop = get_scraper_loop()
    with _lock:
        if _scraper_async_lock is None:
            # Create the lock on the scraper loop safely
            async def _init_lock():
                global _scraper_async_lock
                _scraper_async_lock = asyncio.Lock()
            
            fut = asyncio.run_coroutine_threadsafe(_init_lock(), loop)
            fut.result(timeout=5)
        return _scraper_async_lock


async def _run_with_lock(coro: Coroutine) -> Any:
    lock = get_scraper_lock()
    async with lock:
        return await coro


async def run_scraper_coro(coro: Coroutine, locked: bool = False) -> Any:
    """
    Dispatches a coroutine to the Playwright Proactor loop and awaits its result asynchronously.
    Seamlessly bridges between Uvicorn's main loop and the Playwright worker loop.
    If locked=True, serializes execution using the global scraper lock.
    """
    loop = get_scraper_loop()
    target_coro = _run_with_lock(coro) if locked else coro
    future = asyncio.run_coroutine_threadsafe(target_coro, loop)
    return await asyncio.wrap_future(future)


def run_scraper_coro_sync(coro: Coroutine, timeout: Optional[float] = None, locked: bool = False) -> Any:
    """
    Dispatches a coroutine to the Playwright Proactor loop and blocks synchronously until complete.
    """
    loop = get_scraper_loop()
    target_coro = _run_with_lock(coro) if locked else coro
    future = asyncio.run_coroutine_threadsafe(target_coro, loop)
    return future.result(timeout=timeout)


def shutdown_scraper_loop():
    """Stops the background event loop cleanly."""
    global _scraper_loop
    with _lock:
        if _scraper_loop and not _scraper_loop.is_closed():
            _scraper_loop.call_soon_threadsafe(_scraper_loop.stop)

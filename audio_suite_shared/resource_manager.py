"""
resource_manager.py — Centralized resource management and cleanup.

Provides automatic cleanup of temporary files, thread management,
and resource tracking for the Audio Suite.
"""

import atexit
import logging
import os
import shutil
import tempfile
import threading
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ResourceInfo:
    """Information about a tracked resource."""

    resource_id: str
    resource_type: str  # 'file', 'thread', 'temp_dir', 'subprocess'
    resource_path: Optional[str] = None
    process: Any = None  # subprocess.Popen handle for 'subprocess' type
    created_at: Optional[datetime] = None
    cleanup_callback: Optional[Callable[[], None]] = None
    auto_cleanup: bool = True

    def __post_init__(self) -> None:
        if self.created_at is None:
            self.created_at = datetime.now()


class ResourceManager:
    """Centralized resource management with automatic cleanup."""

    def __init__(self) -> None:
        self._resources: dict[str, ResourceInfo] = {}
        self._cleanup_handlers: dict[str, list[Callable[[], None]]] = {}
        self._lock = threading.Lock()
        self._cleanup_registered = False
        self._temp_dirs: set[str] = set()

        # Register cleanup handlers
        self._register_cleanup_handlers()

    def _register_cleanup_handlers(self) -> None:
        """Register cleanup handlers for various exit scenarios."""
        if self._cleanup_registered:
            return

        # Register atexit handler
        atexit.register(self.cleanup_all_resources)

        self._cleanup_registered = True

    def register_resource(
        self,
        resource_id: str,
        resource_type: str,
        resource_path: Optional[str] = None,
        cleanup_callback: Optional[Callable[[], None]] = None,
        auto_cleanup: bool = True,
    ) -> None:
        """Register a resource for tracking and cleanup.

        Args:
            resource_id: Unique identifier for the resource
            resource_type: Type of resource ('file', 'thread', 'temp_dir', 'subprocess')
            resource_path: Path to the resource (if applicable)
            cleanup_callback: Custom cleanup function
            auto_cleanup: Whether to auto-cleanup on exit
        """
        with self._lock:
            resource_info = ResourceInfo(
                resource_id=resource_id,
                resource_type=resource_type,
                resource_path=resource_path,
                cleanup_callback=cleanup_callback,
                auto_cleanup=auto_cleanup,
            )

            self._resources[resource_id] = resource_info
            logger.debug("Registered resource: %s (%s)", resource_id, resource_type)

    def unregister_resource(self, resource_id: str) -> bool:
        """Unregister a resource (prevent automatic cleanup).

        Args:
            resource_id: Resource identifier

        Returns:
            True if resource was unregistered
        """
        with self._lock:
            if resource_id in self._resources:
                del self._resources[resource_id]
                logger.debug("Unregistered resource: %s", resource_id)
                return True
            return False

    def cleanup_resource(self, resource_id: str) -> bool:
        """Clean up a specific resource.

        Args:
            resource_id: Resource identifier

        Returns:
            True if cleanup was successful
        """
        with self._lock:
            if resource_id not in self._resources:
                logger.warning("Resource not found for cleanup: %s", resource_id)
                return False

            resource = self._resources[resource_id]
            success = False

            try:
                if resource.cleanup_callback:
                    resource.cleanup_callback()
                    success = True
                else:
                    # Default cleanup based on resource type
                    success = self._default_cleanup(resource)

                if success:
                    logger.debug("Cleaned up resource: %s", resource_id)
                    del self._resources[resource_id]

            except (OSError, ProcessLookupError) as e:
                logger.error(
                    "Failed to cleanup resource %s: %s", resource_id, e, exc_info=True
                )
                success = False

            return success

    def _default_cleanup(self, resource: ResourceInfo) -> bool:
        """Default cleanup implementation for different resource types.

        Args:
            resource: Resource information

        Returns:
            True if cleanup was successful
        """
        try:
            if resource.resource_type == "file":
                if resource.resource_path and os.path.exists(resource.resource_path):
                    os.remove(resource.resource_path)
                    logger.debug("Removed file: %s", resource.resource_path)

            elif resource.resource_type == "temp_dir":
                if resource.resource_path and os.path.exists(resource.resource_path):
                    shutil.rmtree(resource.resource_path, ignore_errors=True)
                    self._temp_dirs.discard(resource.resource_path)
                    logger.debug("Removed temp directory: %s", resource.resource_path)

            elif resource.resource_type == "thread":
                # Note: Thread cleanup is handled by weak references
                logger.debug(
                    "Thread resource marked for cleanup: %s",
                    resource.resource_id,
                )

            elif resource.resource_type == "subprocess":
                # Terminate subprocess if still running
                if resource.process is not None:
                    try:
                        resource.process.terminate()
                        resource.process.wait(timeout=5)
                        logger.debug("Terminated subprocess: %s", resource.resource_id)
                    except (OSError, ProcessLookupError, TimeoutError):
                        try:
                            resource.process.kill()
                            logger.debug("Killed subprocess: %s", resource.resource_id)
                        except (OSError, ProcessLookupError) as kill_exc:
                            logger.debug(
                                "Process %s already gone during cleanup: %s",
                                resource.resource_id,
                                kill_exc,
                                exc_info=True,
                            )

            return True

        except (OSError, ProcessLookupError) as e:
            logger.error(
                "Default cleanup failed for %s: %s",
                resource.resource_id,
                e,
                exc_info=True,
            )
            return False

    def cleanup_all_resources(self) -> None:
        """Clean up all registered resources."""
        with self._lock:
            resources_to_cleanup = list(self._resources.items())

        logger.info("Cleaning up %d resources...", len(resources_to_cleanup))

        for resource_id, resource in resources_to_cleanup:
            if resource.auto_cleanup:
                self.cleanup_resource(resource_id)
            else:
                logger.debug("Skipping auto-cleanup for %s", resource_id)

    def cleanup_expired_resources(self, max_age_hours: int = 24) -> int:
        """Clean up resources older than specified age.

        Args:
            max_age_hours: Maximum age in hours before cleanup

        Returns:
            Number of resources cleaned up
        """
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        cleaned_count = 0

        with self._lock:
            expired_resources = [
                (rid, res)
                for rid, res in self._resources.items()
                if res.created_at is not None
                and res.created_at < cutoff_time
                and res.auto_cleanup
            ]

        for resource_id, resource in expired_resources:
            if self.cleanup_resource(resource_id):
                cleaned_count += 1

        if cleaned_count > 0:
            logger.info("Cleaned up %d expired resources", cleaned_count)

        return cleaned_count

    @contextmanager
    def temporary_file(
        self, suffix: str = "", prefix: str = "audio_suite_"
    ) -> Iterator[str]:
        """Context manager for temporary file creation and cleanup.

        Args:
            suffix: File suffix
            prefix: File prefix

        Yields:
            Path to temporary file
        """
        fd, temp_path = tempfile.mkstemp(suffix=suffix, prefix=prefix)
        os.close(fd)  # Close file descriptor, we'll manage the file ourselves

        resource_id = f"temp_file_{Path(temp_path).name}"
        self.register_resource(
            resource_id=resource_id, resource_type="file", resource_path=temp_path
        )

        try:
            yield temp_path
        finally:
            self.cleanup_resource(resource_id)

    @contextmanager
    def temporary_directory(self, prefix: str = "audio_suite_") -> Iterator[str]:
        """Context manager for temporary directory creation and cleanup.

        Args:
            prefix: Directory prefix

        Yields:
            Path to temporary directory
        """
        temp_dir = tempfile.mkdtemp(prefix=prefix)
        self._temp_dirs.add(temp_dir)

        resource_id = f"temp_dir_{Path(temp_dir).name}"
        self.register_resource(
            resource_id=resource_id, resource_type="temp_dir", resource_path=temp_dir
        )

        try:
            yield temp_dir
        finally:
            self.cleanup_resource(resource_id)

    def track_thread(self, thread: threading.Thread, name: Optional[str] = None) -> str:
        """Track a thread for resource management.

        Args:
            thread: Thread to track
            name: Optional name for the thread

        Returns:
            Resource ID for the thread
        """
        if name is None:
            name = f"thread_{thread.ident}"

        resource_id = f"thread_{thread.ident}_{int(datetime.now().timestamp())}"

        # Store weak reference to thread
        thread_ref = weakref.ref(thread)

        def cleanup_thread() -> None:
            thread_obj = thread_ref()
            if thread_obj and thread_obj.is_alive():
                logger.warning("Thread %s is still alive during cleanup", name)

        self.register_resource(
            resource_id=resource_id,
            resource_type="thread",
            cleanup_callback=cleanup_thread,
        )

        logger.debug("Tracking thread: %s (%s)", name, resource_id)
        return resource_id

    @contextmanager
    def tracked_resource(
        self,
        resource_id: str,
        resource_type: str,
        resource_path: Optional[str] = None,
        cleanup_callback: Optional[Callable[[], None]] = None,
    ) -> Iterator[str]:
        """Context manager for general resource tracking and cleanup.

        Args:
            resource_id: Unique identifier
            resource_type: Type of resource
            resource_path: Optional path
            cleanup_callback: Optional custom cleanup
        """
        self.register_resource(
            resource_id=resource_id,
            resource_type=resource_type,
            resource_path=resource_path,
            cleanup_callback=cleanup_callback,
        )
        try:
            yield resource_id
        finally:
            self.cleanup_resource(resource_id)

    def get_resource_stats(self) -> dict[str, int]:
        """Get statistics about managed resources.

        Returns:
            Dictionary with resource counts by type
        """
        with self._lock:
            stats: dict[str, int] = {}
            for resource in self._resources.values():
                resource_type = resource.resource_type
                stats[resource_type] = stats.get(resource_type, 0) + 1
            return stats

    def list_resources(self) -> list[dict[str, Any]]:
        """List all managed resources.

        Returns:
            List of resource information dictionaries
        """
        with self._lock:
            return [
                {
                    "id": res.resource_id,
                    "type": res.resource_type,
                    "path": res.resource_path,
                    "created_at": res.created_at.isoformat()
                    if res.created_at is not None
                    else None,
                    "auto_cleanup": res.auto_cleanup,
                }
                for res in self._resources.values()
            ]


# Global resource manager instance
_resource_manager = None
_resource_manager_lock = threading.Lock()


def get_resource_manager() -> ResourceManager:
    """Get the global resource manager instance."""
    global _resource_manager
    if _resource_manager is None:
        with _resource_manager_lock:
            if _resource_manager is None:
                _resource_manager = ResourceManager()
    return _resource_manager


# Convenience functions
@contextmanager
def temporary_file(suffix: str = "", prefix: str = "audio_suite_") -> Iterator[str]:
    """Create a temporary file with automatic cleanup."""
    manager = get_resource_manager()
    with manager.temporary_file(suffix=suffix, prefix=prefix) as temp_path:
        yield temp_path


@contextmanager
def temporary_directory(prefix: str = "audio_suite_") -> Iterator[str]:
    """Create a temporary directory with automatic cleanup."""
    manager = get_resource_manager()
    with manager.temporary_directory(prefix=prefix) as temp_dir:
        yield temp_dir


def track_thread(thread: threading.Thread, name: Optional[str] = None) -> str:
    """Track a thread for resource management."""
    manager = get_resource_manager()
    return manager.track_thread(thread, name)


def cleanup_expired_resources(max_age_hours: int = 24) -> int:
    """Clean up expired resources."""
    manager = get_resource_manager()
    return manager.cleanup_expired_resources(max_age_hours)


def get_resource_stats() -> dict[str, int]:
    """Get resource management statistics."""
    manager = get_resource_manager()
    return manager.get_resource_stats()

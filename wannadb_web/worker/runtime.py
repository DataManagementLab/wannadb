"""Configure CPU inference lazily inside each web worker's task process."""

import importlib
import logging
import os
from functools import lru_cache

logger = logging.getLogger(__name__)


def _positive_integer(name: str, default: int) -> int:
	"""Read a positive worker thread count from the process environment.

	:param name: The environment variable containing the thread count.
	:type name: str
	:param default: The count used when the variable is absent.
	:type default: int
	:returns: The validated thread count.
	:rtype: int
	:raises ValueError: If the configured count is not a positive integer.
	"""
	try:
		value = int(os.environ.get(name, str(default)))
	except ValueError:
		raise ValueError(f"{name} must be a positive integer.") from None
	if value < 1:
		raise ValueError(f"{name} must be a positive integer.")
	return value


@lru_cache(maxsize=1)
def _configure_torch_threads(pid: int) -> None:
	"""Initialize Torch once for the supplied process identity.

	:param pid: The current PID, also distinguishing a new prefork child in the cache.
	:type pid: int
	:raises ValueError: If a thread count is not a positive integer.
	:raises RuntimeError: If Torch cannot apply the requested inter-op setting.
	"""
	threads = _positive_integer("WANNADB_TORCH_THREADS", 4)
	interop_threads = _positive_integer("WANNADB_TORCH_INTEROP_THREADS", 1)

	torch = importlib.import_module("torch")

	torch.set_num_threads(threads)
	if torch.get_num_interop_threads() != interop_threads:
		torch.set_num_interop_threads(interop_threads)
	logger.info("Worker CPU runtime configured. pid=%s torch_threads=%s torch_interop_threads=%s",
				pid, torch.get_num_threads(), torch.get_num_interop_threads())


def configure_torch_threads() -> None:
	"""Apply the CPU thread budget before this process first loads model resources.

	Keep Torch out of the API and Celery parent process by importing it only
	when a task first needs worker resources. Inter-op parallelism can only
	be configured before inter-op work starts; later tasks reuse that setting.

	:raises ValueError: If a thread count is not a positive integer.
	:raises RuntimeError: If Torch cannot apply the inter-op setting before work.
	"""
	_configure_torch_threads(os.getpid())

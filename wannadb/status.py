import abc
import logging
from typing import Callable

logger: logging.Logger = logging.getLogger(__name__)


class BaseStatusCallback(abc.ABC):
    """
    Base class for all status callbacks.

    A status callback allows the pipeline and its pipeline elements to convey status updates to the user interface. The
    status callback is provided to the pipeline or pipeline element when applying it to the document base. The pipeline
    or pipeline element calls ('__call__') the status callback to convey a status update.

    The status information comprises a message string and a float progress indicator.
    """

    def __call__(self, message: str, progress: float) -> None:
        """
        Convey a status update from the pipeline or pipeline element to the user interface

        This method is called by the pipeline element and calls the _call method that contains the actual implementation
        of the status callback.

        :param message: status message
        :param progress: progress indicator (either between 0.0 and 1.0 or -1 if the progress is unclear)
        """
        if progress == -1:
            logger.info(f"{message} ~%")
        else:
            logger.info(f"{message} {round(progress * 100)}%")

        self._call(message, progress)

    @abc.abstractmethod
    def _call(self, message: str, progress: float) -> None:
        """
        Convey a status update from the pipeline or pipeline element to the user interface

        This method is overwritten by the actual status callbacks and contains their implementation.

        :param message: status message
        :param progress: progress indicator (either between 0.0 and 1.0 or -1 if the progress is unclear)
        """
        raise NotImplementedError


class StatusCallback(BaseStatusCallback):
    """Status callback that is initialized with a callback function."""

    def __init__(self, callback_fn: Callable[[str, float], None]):
        """
        Initialize the status callback.

        :param callback_fn: callback function that is called whenever the interaction callback is called
        """
        self._callback_fn: Callable[[str, float], None] = callback_fn

    def _call(self, message: str, progress: float) -> None:
        return self._callback_fn(message, progress)


class EmptyStatusCallback(BaseStatusCallback):
    """Status callback that does nothing whenever it is called."""

    def _call(self, message: str, progress: float) -> None:
        pass

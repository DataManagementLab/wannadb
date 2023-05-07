import abc
import logging
from typing import Dict, Any, Callable

logger: logging.Logger = logging.getLogger(__name__)


class BaseInteractionCallback(abc.ABC):
    """
    Base class for all interaction callbacks.

    An interaction callback allows pipeline elements to interact with the user. The interaction callback is provided to
    the pipeline element when applying it to the document base. The pipeline element calls ('__call__') the interaction
    callback to interact with the user. The return value of the interaction callback provides the user's feedback to the
    pipeline element.

    Both the parameters and the return values of the interaction callbacks are generic dictionaries, the content of
    which may differ between different implementations.
    """

    def __call__(self, pipeline_element_identifier: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Interaction between the pipeline element and the user.

        This method is called by the pipeline element and calls the _call method that contains the actual implementation
        of the interaction callback.

        :param pipeline_element_identifier: identifier of the calling pipeline element
        :param data: parameters of the feedback request provided to the user interface
        :return: result of the feedback request provided to the pipeline element
        """
        logger.info(f"{pipeline_element_identifier} called the interaction callback.")
        return self._call(pipeline_element_identifier, data)

    @abc.abstractmethod
    def _call(self, pipeline_element_identifier: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Interaction between the pipeline element and the user.

        This method is overwritten by the actual interaction callbacks and contains their implementation.

        :param pipeline_element_identifier: identifier of the calling pipeline element
        :param data: parameters of the feedback request provided to the user interface
        :return: result of the feedback request provided to the pipeline element
        """
        raise NotImplementedError


class InteractionCallback(BaseInteractionCallback):
    """Interaction callback that is initialized with a callback function."""

    def __init__(self, callback_fn: Callable[[str, Dict[str, Any]], Dict[str, Any]]):
        """
        Initialize the interaction callback.

        :param callback_fn: callback function that is called whenever the interaction callback is called
        """
        self._callback_fn: Callable[[str, Dict[str, Any]], Dict[str, Any]] = callback_fn

    def _call(self, pipeline_element_identifier: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._callback_fn(pipeline_element_identifier, data)


class EmptyInteractionCallback(BaseInteractionCallback):
    """Interaction callback that does nothing whenever it is called."""

    def _call(self, pipeline_element_identifier: str, data: Dict[str, Any]) -> Dict[str, Any]:
        pass

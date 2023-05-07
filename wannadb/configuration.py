import abc
import logging
import time
from typing import Any, Dict, List, Type

from wannadb.data.data import DocumentBase
from wannadb.interaction import BaseInteractionCallback
from wannadb.statistics import Statistics
from wannadb.status import BaseStatusCallback

logger = logging.getLogger(__name__)

CONFIGURABLE_ELEMENTS: Dict[str, Type["BaseConfigurableElement"]] = {}


def register_configurable_element(
        configurable_element: Type["BaseConfigurableElement"]
) -> Type["BaseConfigurableElement"]:
    """Register the given configurable element class."""
    CONFIGURABLE_ELEMENTS[configurable_element.identifier] = configurable_element
    return configurable_element


class BaseConfigurableElement(abc.ABC):
    """
    Base class for all configurable elements.

    A configurable element is a class (e.g. pipeline element or pipeline) that can be configured. The element's
    configuration must be serializable ('to_config'), and the exact same element must be reproducible from its
    serialized configuration ('from_config').

    Furthermore, each kind of configurable element must be identifiable by a unique identifier.
    """
    identifier: str = "BaseConfigurableElement"

    def __repr__(self):
        return f"{self.__class__.__name__}()"

    def __str__(self):
        return self.identifier

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self.identifier == other.identifier

    def __hash__(self) -> int:
        return hash(self.identifier)

    @abc.abstractmethod
    def to_config(self) -> Dict[str, Any]:
        """
        Obtain a JSON-serializable representation of the element.

        :return: JSON-serializable representation of the element
        """
        raise NotImplementedError

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "BaseConfigurableElement":
        """
        Create the element from its JSON-serializable representation.

        :param config: JSON-serializable representation of the element
        :return: element created from the JSON-serializable representation
        """
        return CONFIGURABLE_ELEMENTS[config["identifier"]].from_config(config)


class BasePipelineElement(BaseConfigurableElement, abc.ABC):
    """
    Base class for all pipeline elements.

    A pipeline element is a class (e.g. an extractor, embedder, or matcher) that can be applied ('__call__') to a
    document base as part of a pipeline. As such, it works with the data elements' signals. Each pipeline element
    specifies the signals it consumes and the signals it produces for each kind of data element.

    A pipeline element is a configurable element.
    """

    # identifiers of the signals that the pipeline element requires for nuggets, attributes, and documents
    # signals the pipeline element may use if they exist but does not necessarily require are not part of this list
    required_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [],
        "attributes": [],
        "documents": []
    }

    # identifiers of the signals that the pipeline element generates for all nuggets, attributes, and documents
    generated_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [],
        "attributes": [],
        "documents": []
    }

    def _add_required_signal_identifiers(self, required_signal_identifiers: Dict[str, List[str]]) -> None:
        """
        Helper method that adds the dictionary of required signal identifiers to this pipeline element's dictionary of
        required signal identifiers.

        :param required_signal_identifiers: dictionary of required signal identifiers
        """
        for data_element in ["nuggets", "attributes", "documents"]:
            ids: List[str] = self.required_signal_identifiers[data_element] + required_signal_identifiers[data_element]
            self.required_signal_identifiers[data_element] = list(set(ids))

    def __call__(
            self,
            document_base: DocumentBase,
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        """
        Apply the pipeline element to the document base.

        This method is called by the pipeline and calls the _call method that contains the actual implementation of the
        pipeline element. Furthermore, it ensures that the proper status is communicated before and after the pipeline
        element's execution and tracks the execution time.

        :param document_base: document base to work on
        :param interaction_callback: callback to allow for user interaction
        :param status_callback: callback to communicate current status (message and progress)
        :param statistics: statistics object to collect statistics
        """
        logger.info(f"Execute {self.identifier}.")
        tick: float = time.time()
        status_callback(f"Running {self.identifier}...", -1)

        statistics["identifier"] = self.identifier

        self._call(document_base, interaction_callback, status_callback, statistics)

        status_callback(f"Running {self.identifier}...", 1)
        tack: float = time.time()
        logger.info(f"Executed {self.identifier} in {tack - tick} seconds.")
        statistics["runtime"] = tack - tick

    @abc.abstractmethod
    def _call(
            self,
            document_base: DocumentBase,
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        """
        Apply the pipeline element to the document base.

        This method is overwritten by the actual pipeline elements and contains their implementation.

        :param document_base: document base to work on
        :param interaction_callback: callback to allow for user interaction
        :param status_callback: callback to communicate current status (message and progress)
        :param statistics: statistics object to collect statistics
        """
        raise NotImplementedError

    def _use_status_callback(self, status_callback: BaseStatusCallback, ix: int, total: int) -> None:
        """
        Helper method that calls the status callback at regular intervals.

        :param status_callback: callback to communicate current status (message and progress)
        :param ix: index of the current element
        :param total: total number of elements
        """
        if total == 0:
            status_callback(f"Running {self.identifier}...", -1)
        elif ix == 0:
            status_callback(f"Running {self.identifier}...", 0)
        else:
            interval: int = total // 20
            if interval != 0 and ix % interval == 0:
                status_callback(f"Running {self.identifier}...", ix / total)


class Pipeline(BaseConfigurableElement):
    """
    Pipeline that applies pipeline elements to a document base.

    The pipeline can be applied ('__call__') to a document base.

    A pipeline is a configurable element.
    """
    identifier: str = "Pipeline"

    def __init__(self, pipeline_elements: List[BasePipelineElement]) -> None:
        """
        Initialize the Pipeline.

        :param pipeline_elements: list of pipeline elements that make up the pipeline
        """
        super(Pipeline, self).__init__()
        self._pipeline_elements: List[BasePipelineElement] = pipeline_elements

        logger.debug("Initialized the pipeline.")

    def validate_consistency(self, initial_signals: Dict[str, List[str]]) -> bool:
        """
        Validate the consistency of the pipeline regarding required and generated signals.

        This method checks for each pipeline element whether the signals it requires are actually present in the
        document base.

        :param initial_signals: signals that exist in the document base before the pipeline is executed
        :return: True if the pipeline is consistent, else False
        """
        current_signals: Dict[str, List[str]] = initial_signals

        for pipeline_element in self._pipeline_elements:
            for data_element in ["nuggets", "documents", "attributes"]:
                # check that all required signals exist before the pipeline element is executed
                for signal_identifier in pipeline_element.required_signal_identifiers[data_element]:
                    if signal_identifier not in current_signals[data_element]:
                        return False

                # add the newly generated signals to the current signals
                for signal_identifier in pipeline_element.generated_signal_identifiers[data_element]:
                    if signal_identifier not in current_signals[data_element]:
                        current_signals[data_element].append(signal_identifier)

        return True

    @property
    def pipeline_elements(self) -> List[BasePipelineElement]:
        return self._pipeline_elements

    def __str__(self) -> str:
        return f"({', '.join(str(pipeline_element) for pipeline_element in self._pipeline_elements)})"

    def __eq__(self, other) -> bool:
        return isinstance(other, Pipeline) and self._pipeline_elements == other._pipeline_elements

    def __call__(
            self,
            document_base: DocumentBase,
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        """
        Apply the pipeline to the document base.

        :param document_base: document base to work on
        :param interaction_callback: callback to allow for user interaction
        :param status_callback: callback to communicate current status (message and progress)
        :param statistics: statistics object to collect statistics
        """
        logger.info("Execute the pipeline.")
        tick: float = time.time()
        status_callback("Running the pipeline...", -1)

        for ix, pipeline_element in enumerate(self._pipeline_elements):
            pipeline_element(document_base, interaction_callback, status_callback, statistics[f"pipeline-element-{ix}"])

        status_callback("Running the pipeline...", 1)
        tack: float = time.time()
        logger.info(f"Executed the pipeline in {tack - tick} seconds.")
        statistics["runtime"] = tack - tick

    def to_config(self) -> Dict[str, Any]:
        """
        Obtain a JSON-serializable representation of the pipeline.

        :return: JSON-serializable representation of the pipeline
        """
        return {
            "identifier": self.identifier,
            "pipeline_elements": [pipeline_element.to_config() for pipeline_element in self._pipeline_elements]
        }

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "Pipeline":
        """
        Create the pipeline from its JSON-serializable representation.

        :param config: JSON-serializable representation of the pipeline
        :return: pipeline created from the JSON-serializable representation
        """
        return cls(
            [BasePipelineElement.from_config(element_config) for element_config in config["pipeline_elements"]]
        )

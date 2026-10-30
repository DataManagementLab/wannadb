import abc
import logging
from collections.abc import Collection
from typing import Any, Union

import numpy as np
from scipy.spatial.distance import cosine
from sklearn.metrics.pairwise import cosine_distances

from wannadb.configuration import BaseConfigurableElement, register_configurable_element
from wannadb.data.data import Attribute, InformationNugget
from wannadb.data.signals import ContextSentenceEmbeddingSignal, LabelEmbeddingSignal, \
    POSTagsSignal, RelativePositionSignal, TextEmbeddingSignal
from wannadb.statistics import Statistics

logger: logging.Logger = logging.getLogger(__name__)


class BaseDistance(BaseConfigurableElement, abc.ABC):
    """
    Base class for all distance functions.

    Distance functions compute distances between InformationNuggets and Attributes. They must be able to compute distances
    between pairs of InformationNuggets, pairs of Attributes, or mixed pairs.
    """
    identifier: str = "BaseDistance"

    # identifiers of the signals that the distance function requires for nuggets, attributes, and documents
    # signals the distance function may use if they exist but does not necessarily require are not part of this list
    required_signal_identifiers: dict[str, list[str]] = {
        "nuggets": [],
        "attributes": [],
        "documents": []
    }

    @abc.abstractmethod
    def compute_distance(
            self,
            x: Union[InformationNugget, Attribute],
            y: Union[InformationNugget, Attribute],
            statistics: Statistics
    ) -> float:
        """
        Compute distance between the two given InformationNuggets/Attributes.

        :param x: first InformationNugget/Attribute
        :param y: second InformationNugget/Attribute
        :param statistics: statistics object to collect statistics
        :return: computed distance
        """
        raise NotImplementedError

    def compute_distances(
            self,
            xs: Collection[Union[InformationNugget, Attribute]],
            ys: Collection[Union[InformationNugget, Attribute]],
            statistics: Statistics
    ) -> np.ndarray:
        """
        Compute distances between all pairs from two collections of InformationNuggets/Attributes.

        This method exists to speed up the calculation using batching. The default implementation works by calling the
        'compute_distance' method.

        :param xs: first list of InformationNuggets/Attributes
        :param ys: second list of InformationNuggets/Attributes
        :param statistics: statistics object to collect statistics
        :return: matrix of computed distances (row corresponds to xs, column corresponds to ys)
        """
        statistics["num_multi_call"] += 1

        assert len(xs) > 0 and len(ys) > 0, "Cannot compute distances for an empty collection!"

        res: np.ndarray = np.zeros((len(xs), len(ys)))
        for x_ix, x in enumerate(xs):
            for y_ix, y in enumerate(ys):
                res[x_ix, y_ix] = self.compute_distance(x, y, statistics)
        return res


########################################################################################################################
# actual distance functions
########################################################################################################################


@register_configurable_element
class SignalsMeanDistance(BaseDistance):
    """Compute the distance as the mean of the distances between the available signals."""

    identifier: str = "SignalsMeanDistance"

    required_signal_identifiers: dict[str, list[str]] = {
        "nuggets": [
            LabelEmbeddingSignal.identifier
            # can use (but not required): TextEmbeddingSignal.identifier
            # can use (but not required): ContextSentenceEmbeddingSignal.identifier
            # can use (but not required): RelativePositionSignal.identifier
            # can use (but not required): POSTagsSignal.identifier
        ],
        "attributes": [LabelEmbeddingSignal.identifier],
        "documents": []
    }

    def __init__(self, signal_identifiers: list[str]) -> None:
        """
        Initialize the SignalsMeanDistance.

        :param signal_identifiers: identifiers of the signals to include
        """
        super(SignalsMeanDistance, self).__init__()
        self._signal_identifiers: list[str] = list(set(signal_identifiers + [LabelEmbeddingSignal.identifier]))
        logger.debug(f"Initialized '{self.identifier}'.")

    def compute_distance(
            self,
            x: Union[InformationNugget, Attribute],
            y: Union[InformationNugget, Attribute],
            statistics: Statistics
    ) -> float:
        statistics["num_calls"] += 1

        distances: np.ndarray = np.zeros(5)
        is_present: np.ndarray = np.zeros(5)

        label_embedding_signal_identifier: str = LabelEmbeddingSignal.identifier
        if (
                label_embedding_signal_identifier in self._signal_identifiers
                and label_embedding_signal_identifier in x.signals.keys()
                and label_embedding_signal_identifier in y.signals.keys()
        ):
            cosine_distance: float = float(
                cosine(x[label_embedding_signal_identifier], y[label_embedding_signal_identifier]))
            distances[0] = min(abs(cosine_distance), 1)
            is_present[0] = 1

        text_embedding_signal_identifier: str = TextEmbeddingSignal.identifier
        if (
                text_embedding_signal_identifier in self._signal_identifiers
                and text_embedding_signal_identifier in x.signals.keys()
                and text_embedding_signal_identifier in y.signals.keys()
        ):
            cosine_distance: float = float(
                cosine(x[text_embedding_signal_identifier], y[text_embedding_signal_identifier]))
            distances[1] = min(abs(cosine_distance), 1)
            is_present[1] = 1

        context_sentence_embedding_signal_identifier: str = ContextSentenceEmbeddingSignal.identifier
        if (
                context_sentence_embedding_signal_identifier in self._signal_identifiers
                and context_sentence_embedding_signal_identifier in x.signals.keys()
                and context_sentence_embedding_signal_identifier in y.signals.keys()
        ):
            cosine_distance: float = float(
                cosine(x[context_sentence_embedding_signal_identifier], y[context_sentence_embedding_signal_identifier])
            )
            distances[2] = min(abs(cosine_distance), 1)
            is_present[2] = 1

        relative_position_signal_identifier: str = RelativePositionSignal.identifier
        if (
                relative_position_signal_identifier in self._signal_identifiers
                and relative_position_signal_identifier in x.signals.keys()
                and relative_position_signal_identifier in y.signals.keys()
        ):
            relative_distance: float = (x[relative_position_signal_identifier] - y[relative_position_signal_identifier])
            distances[3] = min(abs(relative_distance), 1)
            is_present[3] = 1

        pos_tags_signal_identifier: str = POSTagsSignal.identifier
        if (
                pos_tags_signal_identifier in self._signal_identifiers
                and pos_tags_signal_identifier in x.signals.keys()
                and pos_tags_signal_identifier in y.signals.keys()
        ):
            if x[pos_tags_signal_identifier] == y[context_sentence_embedding_signal_identifier]:
                distances[4] = 0
            else:
                distances[4] = 1  # TODO: magic float, measure "distance"
            is_present[4] = 1

        return 1 if np.sum(is_present) == 0 else np.sum(distances) / np.sum(is_present)

    def compute_distances(
            self,
            xs: Collection[Union[InformationNugget, Attribute]],
            ys: Collection[Union[InformationNugget, Attribute]],
            statistics: Statistics
    ) -> np.ndarray:
        statistics["num_multi_calls"] += 1

        assert len(xs) > 0 and len(ys) > 0, "Cannot compute distances for an empty collection!"
        if not isinstance(xs, list):
            xs = list(xs)
        if not isinstance(ys, list):
            ys = list(xs)

        signal_identifiers: list[str] = [
            LabelEmbeddingSignal.identifier,
            TextEmbeddingSignal.identifier,
            ContextSentenceEmbeddingSignal.identifier,
            RelativePositionSignal.identifier,
            POSTagsSignal.identifier
        ]

        # check that all xs and all ys contain the same signals
        xs_is_present: np.ndarray = np.zeros(5)
        for idx in range(5):
            if signal_identifiers[idx] in self._signal_identifiers and signal_identifiers[idx] in xs[0].signals.keys():
                xs_is_present[idx] = 1
        for x in xs:
            for idx in range(5):
                if signal_identifiers[idx] in self._signal_identifiers:
                    if (
                            xs_is_present[idx] == 1
                            and signal_identifiers[idx] not in x.signals.keys()
                            or xs_is_present[idx] == 0
                            and signal_identifiers[idx] in x.signals.keys()
                    ):
                        assert False, "All xs must have the same signals!"

        ys_is_present: np.ndarray = np.zeros(5)
        for idx in range(5):
            if signal_identifiers[idx] in self._signal_identifiers and signal_identifiers[idx] in ys[0].signals.keys():
                ys_is_present[idx] = 1
        for y in ys:
            for idx in range(5):
                if signal_identifiers[idx] in self._signal_identifiers:
                    if (
                            ys_is_present[idx] == 1
                            and signal_identifiers[idx] not in y.signals.keys()
                            or ys_is_present[idx] == 0
                            and signal_identifiers[idx] in y.signals.keys()
                    ):
                        assert False, "All ys must have the same signals!"

        # compute distances signal by signal
        distances: np.ndarray = np.zeros((len(xs), len(ys)))
        for idx in range(3):
            if xs_is_present[idx] == 1 and ys_is_present[idx] == 1:
                x_embeddings: np.ndarray = np.array([x[signal_identifiers[idx]] for x in xs])
                y_embeddings: np.ndarray = np.array([y[signal_identifiers[idx]] for y in ys])
                tmp: np.ndarray = cosine_distances(x_embeddings, y_embeddings)
                distances = np.add(distances, tmp)

        if xs_is_present[3] == 1 and ys_is_present[3] == 1:
            x_positions: np.ndarray = np.array([x[signal_identifiers[3]] for x in xs])
            y_positions: np.ndarray = np.array([y[signal_identifiers[3]] for y in ys])
            tmp: np.ndarray = np.zeros((len(x_positions), len(y_positions)))
            for x_ix, x_value in enumerate(x_positions):
                for y_ix, y_value in enumerate(y_positions):
                    tmp[x_ix, y_ix] = np.abs(x_value - y_value)
            distances = np.add(distances, tmp)

        if xs_is_present[4] == 1 and ys_is_present[4] == 1:
            x_values: list[list[str]] = [x[signal_identifiers[4]] for x in xs]
            y_values: list[list[str]] = [y[signal_identifiers[4]] for y in ys]
            tmp: np.ndarray = np.ones((len(x_values), len(y_values)))
            for x_ix, x_value in enumerate(x_values):
                for y_ix, y_value in enumerate(y_values):
                    if x_value == y_value:
                        tmp[x_ix, y_ix] = 0
            distances = np.add(distances, tmp)

        actually_present: np.ndarray = xs_is_present * ys_is_present
        if np.sum(actually_present) == 0:
            return np.ones_like(distances)
        else:
            return np.divide(distances, np.sum(actually_present))

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "SignalsMeanDistance":
        return cls(config["signal_identifiers"])

    def to_config(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "signal_identifiers": self._signal_identifiers
        }

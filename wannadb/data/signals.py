import abc
import io
import logging
from typing import Any, Dict, List, Type

import numpy as np

logger: logging.Logger = logging.getLogger(__name__)

SIGNALS: Dict[str, Type["BaseSignal"]] = {}


def register_signal(signal: Type["BaseSignal"]) -> Type["BaseSignal"]:
    """Register the given signal class."""
    SIGNALS[signal.identifier] = signal
    return signal


class BaseSignal(abc.ABC):
    """
    Signals for InformationNuggets, Attributes, and Documents.

    Signals are values that can be set for a given data object (e.g. InformationNugget), but do not necessarily need to be set
    for every data object. Each pipeline element specifies which signals it requires for nuggets, attributes, and
    documents and which signals it generates.

    Signals also specify whether they should be serialized ('do_serialize') and provide their own serialization
    ('to_serializable') and deserialization ('from_serializable') implementation.

    Furthermore, each kind of signal must be identifiable by a unique identifier.
    """
    identifier: str = "BaseSignal"
    do_serialize: bool = False

    def __init__(self, value: Any) -> None:
        """
        Initialize the signal.

        :param value: value of the signal
        """
        super(BaseSignal, self).__init__()
        self._value: Any = value

    def __str__(self) -> str:
        return str(self._value)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({repr(self._value)})"

    def __eq__(self, other) -> bool:
        return isinstance(other, self.__class__) and self._value == other._value

    def __hash__(self) -> int:
        return hash(self.identifier)

    @property
    def value(self) -> Any:
        """Value of the signal."""
        return self._value

    @value.setter
    def value(self, value: Any) -> None:
        """Set the value of the signal."""
        self._value = value

    @abc.abstractmethod
    def to_serializable(self) -> Any:
        """
        Convert the signal to a BSON-serializable representation.

        :return: BSON-serializable representation of the signal
        """
        raise NotImplementedError

    @classmethod
    def from_serializable(cls, serialized_signal: Any, identifier: str) -> "BaseSignal":
        """
        Create a signal from the BSON-serializable representation.

        :param serialized_signal: BSON-serializable representation of the signal
        :param identifier: identifier of the signal kind
        :return: deserialized signal
        """
        return SIGNALS[identifier].from_serializable(serialized_signal, identifier)


class BaseUntypedSignal(BaseSignal, abc.ABC):
    """Base class for all untyped signals"""
    identifier: str = "BaseUntypedSignal"
    do_serialize: bool = False

    @property
    def value(self) -> Any:
        return self._value

    @value.setter
    def value(self, value: Any) -> None:
        self._value = value

    def to_serializable(self) -> Any:
        return self.value

    @classmethod
    def from_serializable(cls, serialized_signal: Any, identifier: str) -> "BaseUntypedSignal":
        return cls(serialized_signal)


class BaseIntSignal(BaseSignal, abc.ABC):
    """Base class for all integer signals."""
    identifier: str = "BaseIntSignal"
    do_serialize: bool = False

    @property
    def value(self) -> int:
        return self._value

    @value.setter
    def value(self, value: int) -> None:
        self._value = value

    def to_serializable(self) -> int:
        return self.value

    @classmethod
    def from_serializable(cls, serialized_signal: int, identifier: str) -> "BaseIntSignal":
        return cls(serialized_signal)


class BaseFloatSignal(BaseSignal, abc.ABC):
    """Base class for all float signals."""
    identifier: str = "BaseFloatSignal"
    do_serialize: bool = False

    @property
    def value(self) -> float:
        return self._value

    @value.setter
    def value(self, value: float) -> None:
        self._value = value

    def to_serializable(self) -> float:
        return self.value

    @classmethod
    def from_serializable(cls, serialized_signal: float, identifier: str) -> "BaseFloatSignal":
        return cls(serialized_signal)


class BaseStringSignal(BaseSignal, abc.ABC):
    """Base class for all string signals."""
    identifier: str = "BaseStringSignal"
    do_serialize: bool = False

    @property
    def value(self) -> str:
        return self._value

    @value.setter
    def value(self, value: str) -> None:
        self._value = value

    def to_serializable(self) -> str:
        return self.value

    @classmethod
    def from_serializable(cls, serialized_signal: str, identifier: str) -> "BaseStringSignal":
        return cls(serialized_signal)


class BaseIntListSignal(BaseSignal, abc.ABC):
    """Base class for all integer list signals."""
    identifier: str = "BaseIntListSignal"
    do_serialize: bool = False

    @property
    def value(self) -> List[int]:
        return self._value

    @value.setter
    def value(self, value: List[int]) -> None:
        self._value = value

    def to_serializable(self) -> List[int]:
        return self.value

    @classmethod
    def from_serializable(cls, serialized_signal: List[int], identifier: str) -> "BaseIntListSignal":
        return cls(serialized_signal)


class BaseFloatListSignal(BaseSignal, abc.ABC):
    """Base class for all float list signals."""
    identifier: str = "BaseIntListSignal"
    do_serialize: bool = False

    @property
    def value(self) -> List[float]:
        return self._value

    @value.setter
    def value(self, value: List[float]) -> None:
        self._value = value

    def to_serializable(self) -> List[float]:
        return self.value

    @classmethod
    def from_serializable(cls, serialized_signal: List[float], identifier: str) -> "BaseFloatListSignal":
        return cls(serialized_signal)


class BaseStringListSignal(BaseSignal, abc.ABC):
    """Base class for all string list signals."""
    identifier: str = "BaseStringListSignal"
    do_serialize: bool = False

    @property
    def value(self) -> List[str]:
        return self._value

    @value.setter
    def value(self, value: List[str]) -> None:
        self._value = value

    def to_serializable(self) -> List[str]:
        return self.value

    @classmethod
    def from_serializable(cls, serialized_signal: List[str], identifier: str) -> "BaseStringListSignal":
        return cls(serialized_signal)


class BaseNumpyArraySignal(BaseSignal, abc.ABC):
    """Base class forall numpy array signals."""
    identifier: str = "BaseNumpyArraySignal"
    do_serialize: bool = False

    def __eq__(self, other) -> bool:
        return isinstance(other, self.__class__) and np.array_equal(self._value, other._value)

    @property
    def value(self) -> np.ndarray:
        return self._value

    @value.setter
    def value(self, value: np.ndarray) -> None:
        self._value = value

    def to_serializable(self) -> bytes:
        save_bytes: io.BytesIO = io.BytesIO()
        # noinspection PyTypeChecker
        np.save(save_bytes, self._value, allow_pickle=True)
        return save_bytes.getvalue()

    @classmethod
    def from_serializable(cls, serialized_signal: bytes, identifier: str) -> "BaseNumpyArraySignal":
        load_bytes: io.BytesIO = io.BytesIO(serialized_signal)
        # noinspection PyTypeChecker
        return cls(np.load(load_bytes, allow_pickle=True))


########################################################################################################################
# actual signals
########################################################################################################################


@register_signal
class ValueSignal(BaseStringSignal):
    """Value of the nugget."""
    identifier: str = "ValueSignal"
    do_serialize: bool = True


@register_signal
class TypeSignal(BaseStringSignal):
    """Type identifier of the nugget's value type."""
    identifier: str = "TypeSignal"
    do_serialize: bool = True


@register_signal
class LabelSignal(BaseFloatSignal):
    """Label of the nugget as determined by the extractors."""
    identifier: str = "LabelSignal"
    do_serialize: bool = True


@register_signal
class NaturalLanguageLabelSignal(BaseStringSignal):
    """Natural language version of the nugget's label that works well with natural language embeddings."""
    identifier: str = "NaturalLanguageLabelSignal"
    do_serialize: bool = True


@register_signal
class RelativePositionSignal(BaseFloatSignal):
    """Relative position of the nugget based on the total length of the document."""
    identifier: str = "RelativePositionSignal"
    do_serialize: bool = True


@register_signal
class CachedContextSentenceSignal(BaseStringSignal):
    """Context sentence and position in context for caching."""
    identifier: str = "CachedContextSentenceSignal"
    do_serialize: bool = False


@register_signal
class CachedDistanceSignal(BaseFloatSignal):
    """Cached distance of the nugget or attribute."""
    identifier: str = "CachedDistanceSignal"
    do_serialize: bool = False


@register_signal
class CurrentMatchIndexSignal(BaseIntSignal):
    """Index of the nugget that is currently considered as the match."""
    identifier: str = "CurrentMatchIndexSignal"
    do_serialize: bool = False


@register_signal
class POSTagsSignal(BaseStringListSignal):
    """POS tags of the nugget's words as determined by extractors."""
    identifier: str = "POSTagsSignal"
    do_serialize: bool = True


@register_signal
class UserProvidedExamplesSignal(BaseStringListSignal):
    """User-provided example values/texts for an attribute."""
    identifier: str = "UserProvidedExamplesSignal"
    do_serialize: bool = True


@register_signal
class SentenceStartCharsSignal(BaseIntListSignal):
    """Sentence boundaries as a list of indices of the first characters in each sentence."""
    identifier: str = "SentenceStartCharsSignal"
    do_serialize: bool = True


@register_signal
class LabelEmbeddingSignal(BaseNumpyArraySignal):
    """Embedding of the nugget's label or attribute's name."""
    identifier: str = "LabelEmbeddingSignal"
    do_serialize: bool = True


@register_signal
class TextEmbeddingSignal(BaseNumpyArraySignal):
    """Embedding of the nugget's text."""
    identifier: str = "TextEmbeddingSignal"
    do_serialize: bool = True


@register_signal
class ContextSentenceEmbeddingSignal(BaseNumpyArraySignal):
    """Embedding of the nugget's textual context sentence."""
    identifier: str = "ContextSentenceEmbeddingSignal"
    do_serialize: bool = True

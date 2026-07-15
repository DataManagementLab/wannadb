import functools
import logging
import time
from typing import Any, Dict, List, Optional, Type, Union, Tuple

import bson

from wannadb.data import signals
from wannadb.data.signals import BaseSignal, ValueSignal

logger: logging.Logger = logging.getLogger(__name__)


class InformationNugget:
    """
    Information piece obtained from a document.

    The information piece corresponds with a span of text in the document (its provenance). Since the InformationNugget does
    not store the actual text but rather the indices of the span in the document, it only functions together with the
    document.

    InformationNuggets can have signals. Signals are values that can be set for a given nugget, but do not necessarily need to
    be set for every nugget.
    """

    def __init__(
            self,
            document: "Document",
            start_char: int,
            end_char: int
    ) -> None:
        """
        Initialize the InformationNugget.

        :param document: document from which it has been obtained
        :param start_char: index of the first character of the span (inclusive)
        :param end_char: index of the first character after the span (exclusive)
        """
        self._document: "Document" = document
        self._start_char: int = start_char
        self._end_char: int = end_char

        self._signals: Dict[str, BaseSignal] = {}

    def __str__(self) -> str:
        return f"'{self.text}'"

    def __repr__(self) -> str:
        return f"InformationNugget({repr(self._document)}, {self._start_char}, {self._end_char})"

    def __hash__(self) -> int:
        # note that two nuggets referring to the same span will always have the same hash value
        return hash((self._document, self._start_char, self._end_char))

    def __eq__(self, other) -> bool:
        return (
                isinstance(other, InformationNugget)
                and self._document.name == other._document.name
                and self._start_char == other._start_char
                and self._end_char == other._end_char
                and self._signals == other._signals
        )

    @property
    def document(self) -> "Document":
        """Document from which the nugget has been derived."""
        return self._document

    @property
    def start_char(self) -> int:
        """Index of the first character of the span (inclusive)."""
        return self._start_char

    @property
    def end_char(self) -> int:
        """Index of the first character after the span (exclusive)."""
        return self._end_char

    @functools.cached_property
    def text(self) -> str:
        """Actual text of the span."""
        return self._document.text[self._start_char:self._end_char]

    @property
    def extractor_name(self) -> str:
        """Name of the extractor that created the nugget."""
        if 'ExtractorNameSignal' not in self._signals.keys():
            return "<UNK>"
        return self._signals['ExtractorNameSignal'].value

    @property
    def serializable(self) -> (str, str, int, int):
        """Serializable representation of the nugget."""
        return self.text, self._document.name, self._start_char, self._end_char, self.extractor_name

    @property
    def signals(self) -> Dict[str, BaseSignal]:
        """Signals associated with the nugget."""
        return self._signals

    def __getitem__(self, item: Union[str, Type[BaseSignal]]) -> Any:
        """
        Get the nugget's signal values.

        :param item: signal class or signal identifier
        :return: value of the signal
        """
        if isinstance(item, str):
            signal_identifier: str = item
        else:
            signal_identifier: str = item.identifier

        return self._signals[signal_identifier].value

    def __setitem__(self, key: Union[str, Type[BaseSignal]], value: Union[BaseSignal, Any]):
        """
        Set the nugget's signal values.

        :param key: signal class or signal identifier
        :param value: signal or signal value
        """
        if isinstance(key, str):
            signal_identifier: str = key
        else:
            signal_identifier: str = key.identifier

        if isinstance(value, BaseSignal):
            self._signals[signal_identifier] = value
        elif signal_identifier in self._signals.keys():
            self._signals[signal_identifier].value = value
        else:  # signal not already set and value is not a signal object ==> get signal class by id and create object
            self._signals[signal_identifier] = signals.SIGNALS[signal_identifier](value)


class Attribute:
    """
    Attribute that is populated with information from the documents.

    An Attribute is a class of information that is obtained from the documents. Each Document may store mappings
    that populate the attribute with InformationNuggets from the document.

    Attributes can have signals. Signals are values that can be set for a given attribute, but do not necessarily
    need to be set for every attribute.
    """

    def __init__(self, name: str) -> None:
        """
        Initialize the Attribute.

        :param name: name of the attribute (must be unique in the document base)
        """
        self._name: str = name

        self._signals: Dict[str, BaseSignal] = {}

    def __str__(self) -> str:
        return f"'{self._name}'"

    def __repr__(self) -> str:
        return f"Attribute('{self._name}')"

    def __hash__(self) -> int:
        return hash(self._name)

    def __eq__(self, other) -> bool:
        return isinstance(other, Attribute) and self._name == other._name and self._signals == other._signals

    @property
    def name(self) -> str:
        """Name of the attribute."""
        return self._name

    @property
    def signals(self) -> Dict[str, BaseSignal]:
        """Signals associated with the attribute."""
        return self._signals

    def __getitem__(self, item: Union[str, Type[BaseSignal]]) -> Any:
        """
        Get the attribute's signal values.

        :param item: signal class or signal identifier
        :return: value of the signal
        """
        if isinstance(item, str):
            signal_identifier: str = item
        else:
            signal_identifier: str = item.identifier

        return self._signals[signal_identifier].value

    def __setitem__(self, key: Union[str, Type[BaseSignal]], value: Union[BaseSignal, Any]):
        """
        Set the attribute's signal values.

        :param key: signal class or signal identifier
        :param value: signal or signal value
        """
        if isinstance(key, str):
            signal_identifier: str = key
        else:
            signal_identifier: str = key.identifier

        if isinstance(value, BaseSignal):
            self._signals[signal_identifier] = value
        elif signal_identifier in self._signals.keys():
            self._signals[signal_identifier].value = value
        else:  # signal not already set and value is not a signal object ==> get signal class by id and create object
            self._signals[signal_identifier] = signals.SIGNALS[signal_identifier](value)


class Document:
    """
    Textual document.

    The Document actually owns the text of the document it represents. It stores a list of all the nuggets derived
    from it. Furthermore, it stores mappings from attribute names to lists of InformationNuggets derived from the document.

    Documents can have signals. Signals are values that can be set for a given document, but do not necessarily need
    to be set for every document.
    """

    def __init__(self, name: str, text: str) -> None:
        """
        Initialize the Document.

        :param name: name of the document (must be unique in the document base)
        :param text: text of the document
        """
        self._name: str = name
        self._text: str = text

        self._nuggets: List[InformationNugget] = []
        self._attribute_mappings: Dict[str, List[InformationNugget]] = {}

        self._signals: Dict[str, BaseSignal] = {}

    def __str__(self) -> str:
        return f"'{self._text}'"

    def __repr__(self) -> str:
        return f"Document('{self._name}', '{self._text}')"

    def __hash__(self) -> int:
        return hash(self._name)

    def __eq__(self, other) -> bool:
        return (
                isinstance(other, Document)
                and self._name == other._name
                and self._text == other._text
                and self._nuggets == other._nuggets
                and self._attribute_mappings == other._attribute_mappings
                and self._signals == other._signals
        )

    @property
    def name(self) -> str:
        """Name of the document."""
        return self._name

    @property
    def text(self) -> str:
        """Text of the document."""
        return self._text

    @property
    def nuggets(self) -> List[InformationNugget]:
        """Nuggets obtained from the document."""
        return self._nuggets

    @property
    def attribute_mappings(self) -> Dict[str, List[InformationNugget]]:
        """Mappings between attribute names and lists of nuggets associated with them."""
        return self._attribute_mappings

    @property
    def signals(self) -> Dict[str, BaseSignal]:
        """Signals associated with the document."""
        return self._signals

    @property
    def sentences(self) -> List[str]:
        """Sentences of the document."""
        # Build sentence list by splitting the text based on start chars in self.signals['SentenceStartCharsSignal']
        sentences = []
        for start_char, end_char in zip(self['SentenceStartCharsSignal'][:-1], self['SentenceStartCharsSignal'][1:]):
            sentences.append(self.text[start_char:end_char])
        sentences.append(self.text[self['SentenceStartCharsSignal'][-1]:])
        return sentences

    def sentence(self, idx: int) -> tuple[int, int, str]:
        """Sentence of the document at the given index."""
        start_char = self['SentenceStartCharsSignal'][idx]
        end_char = self['SentenceStartCharsSignal'][idx + 1] if idx + 1 < len(self['SentenceStartCharsSignal']) else len(self.text)
        return start_char, end_char, self.text[start_char:end_char]

    def __getitem__(self, item: Union[str, Type[BaseSignal]]) -> Any:
        """
        Get the document's signal values.

        :param item: signal class or signal identifier
        :return: value of the signal
        """
        if isinstance(item, str):
            signal_identifier: str = item
        else:
            signal_identifier: str = item.identifier

        return self._signals[signal_identifier].value

    def __setitem__(self, key: Union[str, Type[BaseSignal]], value: Union[BaseSignal, Any]):
        """
        Set the document's signal values.

        :param key: signal class or signal identifier
        :param value: signal or signal value
        """
        if isinstance(key, str):
            signal_identifier: str = key
        else:
            signal_identifier: str = key.identifier

        if isinstance(value, BaseSignal):
            self._signals[signal_identifier] = value
        elif signal_identifier in self._signals.keys():
            self._signals[signal_identifier].value = value
        else:  # signal not already set and value is not a signal object ==> get signal class by id and create object
            self._signals[signal_identifier] = signals.SIGNALS[signal_identifier](value)


class DocumentBase:
    """
    Collection of documents that provides information.

    The DocumentBase manages the documents and attributes. Furthermore, it provides the serialization capabilities
    and the means to validate its consistency.
    """

    def __init__(self, documents: List[Document], attributes: List[Attribute]) -> None:
        """
        Initialize the DocumentBase.

        :param documents: documents of the document base
        :param attributes: attributes of the document base
        """
        self._documents: List[Document] = documents
        self._attributes: List[Attribute] = attributes

    def __str__(self) -> str:
        return f"({len(self._documents)} documents, {len(self.nuggets)} nuggets, {len(self._attributes)} attributes)"

    def __repr__(self) -> str:
        return "DocumentBase([{}], [{}])".format(
            ", ".join(repr(document) for document in self._documents),
            ", ".join(repr(attribute) for attribute in self._attributes)
        )

    def __hash__(self) -> int:
        return hash((tuple(d.name for d in self._documents), tuple(a.name for a in self._attributes)))
    
    def __eq__(self, other) -> bool:
        return (
                isinstance(other, DocumentBase)
                and self._documents == other._documents
                and self._attributes == other._attributes
        )

    @property
    def documents(self) -> List[Document]:
        """Documents of the document base."""
        return self._documents

    @property
    def attributes(self) -> List[Attribute]:
        """Attributes of the document base."""
        return self._attributes

    @property
    def nuggets(self) -> List[InformationNugget]:
        """All nuggets of the document base."""
        nuggets: List[InformationNugget] = []
        for document in self._documents:
            nuggets += document.nuggets
        return nuggets

    def get_nuggets_for_attribute(self, attribute: Union[str, Attribute]) -> List[InformationNugget]:
        """
        List of all nuggets that match the given attribute.

        This list does not encode where the nuggets come from.

        :param attribute: attribute or attribute name
        :return: list of all nuggets that match the given attribute
        """
        if isinstance(attribute, str):
            attribute_name: str = attribute
        else:
            attribute_name: str = attribute.name

        nugget_list: List[InformationNugget] = []
        for document in self._documents:
            if attribute_name in document.attribute_mappings.keys():
                nugget_list += document.attribute_mappings[attribute_name]
        return nugget_list

    def get_column_for_attribute(self, attribute: Union[str, Attribute]) -> List[Optional[List[InformationNugget]]]:
        """
        Column of nuggets that match the given attribute.

        The column of nuggets is a list that for each document contains either a (possibly empty) list of matching
        nuggets or None in case the document does not know of the Attribute.

        ========================
        | [nugget-1, nugget-2] |
        | None                 |
        | [nugget-4]           |
        | []                   |
        ========================

        :param attribute: attribute or attribute name
        :return: column of nuggets that match the given attribute
        """
        if isinstance(attribute, str):
            attribute_name: str = attribute
        else:
            attribute_name: str = attribute.name

        nugget_column: List[Optional[List[InformationNugget]]] = []
        for document in self._documents:
            if attribute_name in document.attribute_mappings.keys():
                nugget_column.append(document.attribute_mappings[attribute_name])
            else:
                nugget_column.append(None)
        return nugget_column

    def to_table_dict(
            self, kind: Optional[str] = None
    ) -> Dict[str, List[Union[None, str, List[InformationNugget], List[Union[str, None]]]]]:
        """
        Table representation of the information nuggets in the document base.

        The table is stored as a dictionary of columns. It uses the names of attributes and documents, and the parameter
        'kind' determines whether the nuggets' *text*, *value*, or the nuggets themselves should be stored. A cell can
        either be None, in which case the Document does not know of the Attribute, or a (possibly empty) list of
        texts/values/nuggets.

        =================================================================
        | 'document-name' | 'attribute-1'        | 'attribute-2'        |
        =================================================================
        | 'document-1'    | [nugget-1, nugget-2] | []                   |
        | 'document-2'    | None                 | [nugget-5]           |
        | 'document-3'    | [nugget-4]           | [nugget-6, nugget-7] |
        =================================================================

        :param kind: whether the nuggets *text*, *value*, or the nuggets themselves (*None*) should be stored.
        :return: table representation of the information nuggets in the document base
        """
        result: Dict[
            str, List[Union[None, str, List[InformationNugget], List[Union[str, None]]]]
        ] = {
            "document-name": [document.name for document in self._documents]
        }

        for attribute in self._attributes:
            result[attribute.name] = []
            for document in self._documents:
                if kind is None:
                    if attribute.name in document.attribute_mappings.keys():
                        result[attribute.name].append(document.attribute_mappings[attribute.name])
                    else:
                        result[attribute.name].append(None)
                elif kind == "text":
                    if attribute.name in document.attribute_mappings.keys():
                        result[attribute.name].append([
                            nugget.text for nugget in document.attribute_mappings[attribute.name]
                        ])
                    else:
                        result[attribute.name].append(None)
                elif kind == "value":
                    if attribute.name in document.attribute_mappings.keys():
                        result[attribute.name].append([
                            str(nugget[ValueSignal]) if ValueSignal.identifier in nugget.signals.keys() else None
                            for nugget in document.attribute_mappings[attribute.name]
                        ])
                    else:
                        result[attribute.name].append(None)
                else:
                    assert False, f"Unknown parameter kind '{kind}'!"

        return result

    def validate_consistency(self) -> bool:
        """Validate the consistency of the document base."""
        tick: float = time.time()

        # check that the document names are unique
        if not len([d.name for d in self._documents]) == len(set([d.name for d in self._documents])):
            print("Document names are not unique.")
            return False

        # check that the attribute names are unique
        if not len([a.name for a in self._attributes]) == len(set([a.name for a in self._attributes])):
            print("Attribute names are not unique.")
            return False

        # check that all nuggets in a document refer to that document
        for document in self._documents:
            for nugget in document.nuggets:
                if nugget.document is not document:
                    print(f"Nugget '{nugget}' does not refer to the document it is stored in.")
                    return False

        # check that the nuggets' span indices are valid
        for nugget in self.nuggets:
            if not 0 <= nugget.start_char < nugget.end_char <= len(nugget.document.text):
                print(f"Nugget '{nugget}' has invalid span indices.")
                return False

        # check that all attribute names in attribute mappings are part of the document base
        for document in self._documents:
            for attribute_name in document.attribute_mappings.keys():
                if attribute_name not in [attribute.name for attribute in self._attributes]:
                    logger.warning(f"Attribute '{attribute_name}' in document '{document.name}' is not part of the document base.")
                    print(f"Attribute '{attribute_name}' in document '{document.name}' is not part of the document base.")
                    return False

        # check that all nuggets referred to in attribute mappings are part of the document
        for document in self._documents:
            for nuggets in document.attribute_mappings.values():
                for nugget in nuggets:
                    for nug in document.nuggets:
                        if nug is nugget:
                            break
                    else:
                        print(f"Nugget '{nugget}' in document '{document.name}' is not part of the document.")
                        return False

        # check that all nugget signals are stored under their own signal identifier
        for nugget in self.nuggets:
            for signal_identifier, signal in nugget.signals.items():
                if signal_identifier != signal.identifier:
                    print(f"Signal '{signal}' in nugget '{nugget}' is not stored under its own signal identifier.")
                    return False

        # check that all attribute signals are stored under their own signal identifier
        for attribute in self._attributes:
            for signal_identifier, signal in attribute.signals.items():
                if signal_identifier != signal.identifier:
                    print(f"Signal '{signal}' in attribute '{attribute}' is not stored under its own signal identifier.")
                    return False

        # check that all document signals are stored under their own signal identifier
        for document in self._documents:
            for signal_identifier, signal in document.signals.items():
                if signal_identifier != signal.identifier:
                    print(f"Signal '{signal}' in document '{document}' is not stored under its own signal identifier.")
                    return False

        tack: float = time.time()
        logger.info(f"Validated document base consistency in {tack - tick} seconds.")
        return True

    def to_bson(self, save_attribute_mappings: bool = True) -> bytes:
        """
        Serialize the document base to a BSON byte string.

        https://pymongo.readthedocs.io/en/stable/api/bson/index.html

        :param save_attribute_mappings: whether the attribute mappings should be saved in the BSON representation,
                                        this is needed for the matching replay, where the attribute mappings are not
                                        relevant and can be reconstructed from the history of match decisions. Default is True.
        :return: BSON byte representation of the document base
        """
        tick: float = time.time()

        # validate document base consistency
        if not self.validate_consistency():
            logger.error("Cannot serialize an inconsistent document base!")
            assert False, "Cannot serialize an inconsistent document base!"

        # serialize the document base
        serializable_base: Dict[str, Any] = {"documents": [], "attributes": []}

        logger.info("Serialize attributes.")
        for attribute in self._attributes:
            # serialize the attribute
            serializable_attribute: Dict[str, Any] = {
                "name": attribute.name,
                "signals": {}
            }

            # serialize the signals
            for signal_identifier, signal in attribute.signals.items():
                if signal.do_serialize:
                    serializable_attribute["signals"][signal_identifier] = signal.to_serializable()

            serializable_base["attributes"].append(serializable_attribute)

        logger.info("Serialize documents.")
        for document in self._documents:
            # serialize the document
            serializable_document: Dict[str, Any] = {
                "name": document.name,
                "text": document.text,
                "nuggets": [],
                "attribute_mappings": {},
                "signals": {}
            }

            if save_attribute_mappings:
                # serialize the attribute mappings
                for name, nuggets in document.attribute_mappings.items():
                    nugget_ids: List[int] = []
                    for nugget in nuggets:
                        for idx, doc_nugget in enumerate(document.nuggets):
                            if nugget is doc_nugget:
                                nugget_ids.append(idx)
                                break
                        else:
                            assert False, "The document does not contain the nugget that is assigned to the attribute."

                    serializable_document["attribute_mappings"][name] = nugget_ids

            # serialize the signals
            for signal_identifier, signal in document.signals.items():
                if signal.do_serialize:
                    serializable_document["signals"][signal_identifier] = signal.to_serializable()

            for nugget in document.nuggets:
                # serialize the nugget
                serializable_nugget: Dict[str, Any] = {
                    "start_char": nugget.start_char,
                    "end_char": nugget.end_char,
                    "signals": {}
                }

                # serialize the signals
                for signal_identifier, signal in nugget.signals.items():
                    if signal.do_serialize:
                        serializable_nugget["signals"][signal_identifier] = signal.to_serializable()

                serializable_document["nuggets"].append(serializable_nugget)
            serializable_base["documents"].append(serializable_document)

        logger.info("Convert to BSON bytes.")
        bson_bytes: bytes = bson.encode(serializable_base)

        tack: float = time.time()
        logger.info(f"Serialized document base in {tack - tick} seconds.")

        return bson_bytes

    @classmethod
    def from_bson(cls, bson_bytes: bytes) -> "DocumentBase":
        """
        Deserialize a document base from a BSON byte string.

        https://pymongo.readthedocs.io/en/stable/api/bson/index.html

        :param bson_bytes: BSON byte representation of the document base
        :return: document base created from the BSON byte string
        """
        tick: float = time.time()

        logger.info("Convert from BSON bytes.")
        serialized_base: Dict[str, Any] = bson.decode(bson_bytes)

        # deserialize the document base
        document_base: "DocumentBase" = cls([], [])

        logger.info("Deserialize attributes.")
        for serialized_attribute in serialized_base["attributes"]:
            # deserialize the attribute
            attribute: Attribute = Attribute(name=serialized_attribute["name"])

            # deserialize the signals
            for signal_identifier, serialized_signal in serialized_attribute["signals"].items():
                signal: BaseSignal = BaseSignal.from_serializable(serialized_signal, signal_identifier)
                attribute.signals[signal_identifier] = signal

            document_base.attributes.append(attribute)

        logger.info("Deserialize documents.")
        for serialized_document in serialized_base["documents"]:
            # deserialize the document
            document: Document = Document(name=serialized_document["name"], text=serialized_document["text"])

            for serialized_nugget in serialized_document["nuggets"]:
                # deserialize the nugget
                nugget: InformationNugget = InformationNugget(
                    document=document,
                    start_char=serialized_nugget["start_char"],
                    end_char=serialized_nugget["end_char"]
                )

                # deserialize the signals
                for signal_identifier, serialized_signal in serialized_nugget["signals"].items():
                    signal: BaseSignal = BaseSignal.from_serializable(serialized_signal, signal_identifier)
                    nugget.signals[signal_identifier] = signal

                document.nuggets.append(nugget)

            # deserialize the attribute mappings
            for name, indices in serialized_document["attribute_mappings"].items():
                document.attribute_mappings[name] = [document.nuggets[idx] for idx in indices]

            # deserialize the signals
            for signal_identifier, serialized_signal in serialized_document["signals"].items():
                signal: BaseSignal = BaseSignal.from_serializable(serialized_signal, signal_identifier)
                document.signals[signal_identifier] = signal

            document_base.documents.append(document)

        # validate document base consistency
        if not document_base.validate_consistency():
            logger.error("Cannot deserialize an inconsistent document base!")
            assert False, "Cannot deserialize an inconsistent document base!"

        tack: float = time.time()
        logger.info(f"Deserialized document base in {tack - tick} seconds.")

        return document_base


class MatchingEvent:
    """
    Event that occurs during the matching process.

    A MatchingEvent encodes an event that occurs during the matching process. It contains all information about the event,
    such as the document base, the attribute for which a match is searched, the document and nugget for which a match has
    been found or not found, and the feedback result of the user interaction.
    """

    def __init__(
            self,
            action: str,
            document_base: DocumentBase,
            attribute: Attribute,
            document: Document,
            nugget: Optional[InformationNugget],
            max_distance: float,
            not_a_match: Optional[InformationNugget] = None,
            correct_action: Optional[str] = None,
            revert_event_id: Optional[int] = None
    ) -> None:
        """
        Initialize the MatchingEvent.
        
        :param action: action that was performed, e.g., "match-found", "no-match-in-document", "no-match-in-base"
        :type action: str
        :param document_base: the document base for which the event occurred
        :type document_base: DocumentBase
        :param attribute: the attribute for which the event occurred
        :type attribute: Attribute
        :param document: the document for which the event occurred
        :type document: Document
        :param nugget: the nugget for which the event occurred (can be None if no match was found)
        :type nugget: Optional[InformationNugget]
        :param max_distance: the maximum distance before the match is handled
        :type max_distance: float
        :param not_a_match: the nugget that was not a match (can be None if no match was found)
        :type not_a_match: Optional[InformationNugget]
        :param correct_action: the correct action that should have been performed (if any)
        :type correct_action: Optional[str]
        :param revert_event_id: the id of the event that is being reverted (if any)
        :type revert_event_id: Optional[int]
        """
        self.action = action
        self.document_base = document_base
        self.attribute = attribute
        self.document = document
        self.nugget = nugget
        self.not_a_match = not_a_match
        self.max_distance = max_distance
        self.correct_action = correct_action
        self.revert_event_id = revert_event_id
        
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the MatchingEvent to a dictionary.

        :return: dictionary representation of the MatchingEvent
        """
        return {
            "action": self.action,
            "attribute": self.attribute.name,
            "document": self.document.name,
            "nugget": {
                "text": self.nugget.text,
                "start_char": self.nugget.start_char,
                "end_char": self.nugget.end_char
            } if self.nugget is not None else None,
            "not_a_match": {
                "text": self.not_a_match.text,
                "start_char": self.not_a_match.start_char,
                "end_char": self.not_a_match.end_char
            } if self.not_a_match is not None else None,
            "correct_action": self.correct_action,
            "revert_event_id": self.revert_event_id,
            "max_distance": self.max_distance
        }
        
    @staticmethod
    def from_dict(data: Dict[str, Any], document_base: DocumentBase) -> "MatchingEvent":
        """
        Create a MatchingEvent from a dictionary.

        :param data: dictionary representation of the MatchingEvent
        :type data: Dict[str, Any]
        :param document_base: the DocumentBase object to which the MatchingEvent belongs (needed to resolve the attribute, document, and nugget objects)
        :type document_base: DocumentBase
        :return: MatchingEvent created from the dictionary
        :rtype: MatchingEvent
        :raises ValueError: if the attribute, document, or nugget specified in the dictionary cannot be found in the document base
        """
        for _attribute in document_base.attributes:
            if _attribute.name == data["attribute"]:
                attribute = _attribute
                break
        else:
            raise ValueError(f"Attribute '{data['attribute']}' not found in document base.")
        for _document in document_base.documents:
            if _document.name == data["document"]:
                document = _document
                break
        else:
            raise ValueError(f"Document '{data['document']}' not found in document base.")
        if data["nugget"] is not None:
            for _nugget in document.nuggets:
                if _nugget.text == data["nugget"]["text"] and _nugget.start_char == data["nugget"]["start_char"] and _nugget.end_char == data["nugget"]["end_char"]:
                    nugget = _nugget
                    break
            else:
                raise ValueError(f"Nugget '{data['nugget']}' not found in document '{document.name}'.")
        else:
            nugget = None
        if data["not_a_match"] is not None:
            for _nugget in document.nuggets:
                if _nugget.text == data["not_a_match"]["text"] and _nugget.start_char == data["not_a_match"]["start_char"] and _nugget.end_char == data["not_a_match"]["end_char"]:
                    not_a_match = _nugget
                    break
            else:
                raise ValueError(f"Not-a-match nugget '{data['not_a_match']}' not found in document '{document.name}'.")
        else:
            not_a_match = None
        return MatchingEvent(
            action=data["action"],
            document_base=document_base,
            attribute=attribute,
            document=document,
            nugget=nugget,
            not_a_match=not_a_match,
            max_distance=data["max_distance"],
            correct_action=None if data["action"] != "revert-event" else data.get("correct_action", None),
            revert_event_id=data.get("revert_event_id", None)
        )

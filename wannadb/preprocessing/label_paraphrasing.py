import abc
import logging
import time
from typing import Dict, List, Any

from wannadb.configuration import BasePipelineElement, register_configurable_element
from wannadb.data.data import DocumentBase, InformationNugget, Attribute
from wannadb.data.signals import LabelSignal, NaturalLanguageLabelSignal
from wannadb.interaction import BaseInteractionCallback
from wannadb.statistics import Statistics
from wannadb.status import BaseStatusCallback

logger: logging.Logger = logging.getLogger(__name__)


class BaseLabelParaphraser(BasePipelineElement, abc.ABC):
    """
    Base class for all label paraphrasers.

    Label paraphrasers translate NER-tags (in the case of information nuggets) or column titles (in the case of
    attributes) into a natural language string that works well with natural language embeddings.
    """
    identifier: str = "BaseLabelParaphraser"

    def _use_status_callback_for_label_paraphrasers(
            self,
            status_callback: BaseStatusCallback,
            element: str,
            ix: int,
            total: int
    ) -> None:
        """
        Helper method that calls the status callback at regular intervals.

        :param status_callback: status callback to call
        :param element: 'nugget labels' or 'attribute names'
        :param ix: index of the current element
        :param total: total number of elements
        """
        if total == 0:
            status_callback(f"Paraphrasing {element} with {self.identifier}...", -1)
        elif ix == 0:
            status_callback(f"Paraphrasing {element} with {self.identifier}...", 0)
        else:
            interval: int = total // 10
            if interval != 0 and ix % interval == 0:
                status_callback(f"Paraphrasing {element} with {self.identifier}...", ix / total)

    def _call(
            self,
            document_base: DocumentBase,
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        # paraphrasing nugget labels
        nuggets: List[InformationNugget] = document_base.nuggets
        logger.info(f"Paraphrase {len(nuggets)} nugget labels with {self.identifier}.")
        tick: float = time.time()
        status_callback(f"Paraphrasing nugget labels with {self.identifier}...", -1)
        statistics["nuggets"]["num_nuggets"] = len(nuggets)
        self._paraphrase_nugget_labels(nuggets, interaction_callback, status_callback, statistics["nuggets"])
        status_callback(f"Paraphrasing nugget labels with {self.identifier}...", 1)
        tack: float = time.time()
        logger.info(f"Paraphrased {len(nuggets)} nugget labels with {self.identifier} in {tack - tick} seconds.")
        statistics["nuggets"]["runtime"] = tack - tick

        # paraphrasing attribute names
        attributes: List[Attribute] = document_base.attributes
        logger.info(f"Paraphrase {len(attributes)} attribute names with {self.identifier}.")
        tick: float = time.time()
        status_callback(f"Paraphrasing attribute names with {self.identifier}...", -1)
        statistics["attributes"]["num_attributes"] = len(nuggets)
        self._paraphrase_attribute_names(attributes, interaction_callback, status_callback, statistics["attributes"])
        status_callback(f"Paraphrasing attribute names with {self.identifier}...", 1)
        tack: float = time.time()
        logger.info(f"Paraphrased {len(attributes)} attribute names with {self.identifier} in {tack - tick} seconds.")
        statistics["attributes"]["runtime"] = tack - tick

    def _paraphrase_nugget_labels(
            self,
            nuggets: List[InformationNugget],
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        """
        Paraphrase nugget labels for the given list of nuggets.

        :param nuggets: list of nuggets to work on
        :param interaction_callback: callback to allow for user interaction
        :param status_callback: callback to communicate current status (message and progress)
        :param statistics: statistics object to collect statistics
        """
        pass  # default behavior: do nothing

    def _paraphrase_attribute_names(
            self,
            attributes: List[Attribute],
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        """
        Paraphrase attribute names for the given list of InformationNuggets.

        :param attributes: list of Attributes to work on
        :param interaction_callback: callback to allow for user interaction
        :param status_callback: callback to communicate current status (message and progress)
        :param statistics: statistics object to collect statistics
        """
        pass  # default behavior: do nothing


########################################################################################################################
# actual label paraphrasers
########################################################################################################################


@register_configurable_element
class OntoNotesLabelParaphraser(BaseLabelParaphraser):
    """Label paraphraser for OntoNotes NER tags based on their definition."""
    identifier: str = "OntoNotesLabelParaphraser"

    required_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [LabelSignal.identifier],
        "attributes": [],
        "documents": []
    }

    generated_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [NaturalLanguageLabelSignal.identifier],
        "attributes": [],
        "documents": []
    }

    def __init__(self):
        """Initialize the OntoNotesLabelParaphraser."""
        super(OntoNotesLabelParaphraser, self).__init__()
        logger.debug(f"Initialized '{self.identifier}'.")

    def _paraphrase_nugget_labels(
            self,
            nuggets: List[InformationNugget],
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        statistics["num_nuggets"] = len(nuggets)
        statistics["copied_labels"] = set()

        for ix, nugget in enumerate(nuggets):
            self._use_status_callback_for_label_paraphrasers(status_callback, "nugget labels", ix, len(nuggets))
            label_mappings: Dict[str, str] = {
                "QUANTITY": "quantity measurement weight distance",
                "CARDINAL": "cardinal numeral",
                "NORP": "nationality religion political group",
                "FAC": "building airport highway bridge",
                "ORG": "organization",
                "GPE": "country city state",
                "LOC": "location mountain range body of water",
                "PRODUCT": "product vehicle weapon food",
                "EVENT": "event hurricane battle war sports",
                "WORK_OF_ART": "work of art title of book song",
                "LAW": "law document",
                "LANGUAGE": "language",
                "ORDINAL": "ordinal",
                "MONEY": "money",
                "PERCENT": "percentage",
                "DATE": "date period",
                "TIME": "time",
                "PERSON": "person",
            }

            if nugget[LabelSignal] in label_mappings.keys():
                natural_language_label: str = label_mappings[nugget[LabelSignal]]
                nugget[NaturalLanguageLabelSignal] = NaturalLanguageLabelSignal(natural_language_label)
                statistics["num_label_changed"] += 1
            else:
                nugget[NaturalLanguageLabelSignal] = NaturalLanguageLabelSignal(nugget[LabelSignal])
                statistics["num_label_copied"] += 1
                statistics["copied_labels"].add(nugget[LabelSignal])

    def to_config(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier
        }

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "OntoNotesLabelParaphraser":
        return cls()


@register_configurable_element
class CopyAttributeNameLabelParaphraser(BaseLabelParaphraser):
    """Label paraphraser that simply copies the attribute name as the natural language label signal."""
    identifier: str = "CopyAttributeNameLabelParaphraser"

    def __init__(self):
        """Initialize the CopyAttributeNameLabelParaphraser."""
        super(CopyAttributeNameLabelParaphraser, self).__init__()
        logger.debug(f"Initialized '{self.identifier}'.")

    required_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [],
        "attributes": [],
        "documents": []
    }

    generated_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [],
        "attributes": [NaturalLanguageLabelSignal.identifier],
        "documents": []
    }

    def _paraphrase_attribute_names(
            self,
            attributes: List[Attribute],
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        statistics["num_attributes"] = len(attributes)

        for ix, attribute in enumerate(attributes):
            self._use_status_callback_for_label_paraphrasers(status_callback, "attribute names", ix, len(attributes))
            attribute[NaturalLanguageLabelSignal] = NaturalLanguageLabelSignal(attribute.name)
            statistics["num_label_copied"] += 1

    def to_config(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier
        }

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "CopyAttributeNameLabelParaphraser":
        return cls()


@register_configurable_element
class SplitAttributeNameLabelParaphraser(BaseLabelParaphraser):
    """Label paraphraser that splits the attribute name to generate the natural language label signal."""
    identifier: str = "SplitAttributeNameLabelParaphraser"

    required_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [],
        "attributes": [],
        "documents": []
    }

    generated_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [],
        "attributes": [NaturalLanguageLabelSignal.identifier],
        "documents": []
    }

    def __init__(self, do_lowercase: bool, splitters: List[str]) -> None:
        """
        Initialize the SplitAttributeNameLabelParaphraser.

        :param do_lowercase: whether to lowercase the attribute names
        :param splitters: characters at which the attribute name should be split
        """
        super(SplitAttributeNameLabelParaphraser, self).__init__()
        self._do_lowercase: bool = do_lowercase
        self._splitters: List[str] = splitters
        logger.debug(f"Initialized '{self.identifier}'.")

    def _paraphrase_attribute_names(
            self,
            attributes: List[Attribute],
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        statistics["num_attributes"] = len(attributes)

        for ix, attribute in enumerate(attributes):
            self._use_status_callback_for_label_paraphrasers(status_callback, "attribute names", ix, len(attributes))

            # tokenize the label
            tokens: List[str] = [attribute.name]
            for splitter in self._splitters:
                new_tokens: List[str] = []
                for token in tokens:
                    new_tokens += token.split(splitter)
                tokens: List[str] = new_tokens

            # lowercase the tokens
            if self._do_lowercase:
                tokens: List[str] = [token.lower() for token in tokens]

            attribute[NaturalLanguageLabelSignal] = NaturalLanguageLabelSignal(" ".join(tokens))
            if " ".join(tokens) == attribute.name:
                statistics["num_label_unchanged"] += 1
            else:
                statistics["num_label_changed"] += 1

    def to_config(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier,
            "do_lowercase": self._do_lowercase,
            "splitters": self._splitters
        }

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "SplitAttributeNameLabelParaphraser":
        return cls(config["do_lowercase"], config["splitters"])

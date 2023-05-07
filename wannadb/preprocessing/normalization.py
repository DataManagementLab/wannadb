import abc
import logging
from typing import Any, Dict, List

from wannadb.configuration import register_configurable_element, BasePipelineElement
from wannadb.data.data import DocumentBase, InformationNugget
from wannadb.data.signals import LabelSignal, ValueSignal
from wannadb.interaction import BaseInteractionCallback
from wannadb.statistics import Statistics
from wannadb.status import BaseStatusCallback

logger: logging.Logger = logging.getLogger(__name__)


class BaseNormalizer(BasePipelineElement, abc.ABC):
    """
    Base class for all normalizers.

    Normalizers derive the value of an information nuggets from its mention text.
    """
    identifier: str = "BaseNormalizer"


########################################################################################################################
# actual normalizers
########################################################################################################################


@register_configurable_element
class CopyNormalizer(BaseNormalizer):
    """
    Normalizer that simply uses the nuggets' mention texts as their values if the value signal does not already exist.
    """
    identifier: str = "CopyNormalizer"

    required_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [],
        "attributes": [],
        "documents": []
    }

    generated_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [ValueSignal.identifier],
        "attributes": [],
        "documents": []
    }

    def __init__(self) -> None:
        super(CopyNormalizer, self).__init__()

        logger.debug(f"Initialized '{self.identifier}'.")

    def _call(
            self,
            document_base: DocumentBase,
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        nuggets: List[InformationNugget] = document_base.nuggets  # document_base.nuggets has overhead
        statistics["num_nuggets"] = len(nuggets)

        for ix, nugget in enumerate(nuggets):
            self._use_status_callback(status_callback, ix, len(nuggets))

            if ValueSignal.identifier not in nugget.signals.keys():
                statistics["num_value_set"] += 1
                nugget[ValueSignal] = ValueSignal(nugget.text)
            else:
                statistics["num_value_already_exists"] += 1

    def to_config(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier
        }

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "CopyNormalizer":
        return cls()


@register_configurable_element
class VerySimpleDateNormalizer(BaseNormalizer):
    identifier: str = "VerySimpleDateNormalizer"

    required_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [LabelSignal.identifier],
        "attributes": [],
        "documents": []
    }

    generated_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [ValueSignal.identifier],
        "attributes": [],
        "documents": []
    }

    def __init__(self) -> None:
        super(VerySimpleDateNormalizer, self).__init__()

        logger.debug(f"Initialized '{self.identifier}'.")

    def _call(
            self,
            document_base: DocumentBase,
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        nuggets: List[InformationNugget] = document_base.nuggets  # document_base.nuggets has overhead
        statistics["num_nuggets"] = len(nuggets)
        statistics["date_value_failed"] = set()

        for ix, nugget in enumerate(nuggets):
            self._use_status_callback(status_callback, ix, len(nuggets))

            if nugget[LabelSignal] == "DATE":
                year = nugget.text[-4:]

                month_mapping = {
                    "January": "01",
                    "February": "02",
                    "March": "03",
                    "April": "04",
                    "May": "05",
                    "June": "06",
                    "July": "07",
                    "August": "08",
                    "September": "09",
                    "October": "10",
                    "November": "11",
                    "December": "12"
                }
                if " " in nugget.text:
                    month = nugget.text[:nugget.text.index(" ")]
                    if month in month_mapping.keys() and " " in nugget.text and "," in nugget.text:
                        month = month_mapping[month]
                        day = nugget.text[nugget.text.index(" ") + 1:nugget.text.index(",")]
                        day = day.rjust(2, "0")
                        nugget[ValueSignal] = ValueSignal(f"{year}-{month}-{day}")
                        statistics["num_date_value_set"] += 1
                        continue

                nugget[ValueSignal] = ValueSignal(nugget.text)
                statistics["num_date_value_failed"] += 1
                statistics["date_value_failed"].add(nugget.text)
            else:
                nugget[ValueSignal] = ValueSignal(nugget.text)
                statistics["num_other_value_copied"] += 1

    def to_config(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier
        }

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "VerySimpleDateNormalizer":
        return cls()

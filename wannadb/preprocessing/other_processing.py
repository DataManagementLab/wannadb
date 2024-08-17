import logging
from typing import Dict, List, Any

from wannadb.configuration import BasePipelineElement, register_configurable_element
from wannadb.data.data import DocumentBase, InformationNugget
from wannadb.data.signals import CachedContextSentenceSignal, \
    SentenceStartCharsSignal, TextEmbeddingSignal, CurrentMatchIndexSignal
from wannadb.interaction import BaseInteractionCallback
from wannadb.statistics import Statistics
from wannadb.status import BaseStatusCallback
from wannadb.utils import get_possible_duplicate

logger: logging.Logger = logging.getLogger(__name__)


@register_configurable_element
class ContextSentenceCacher(BasePipelineElement):
    """Caches a nugget's context sentence."""

    identifier: str = "ContextSentenceCacher"

    required_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [],
        "attributes": [],
        "documents": [SentenceStartCharsSignal.identifier]
    }

    generated_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [CachedContextSentenceSignal.identifier],
        "attributes": [],
        "documents": []
    }

    def __init__(self):
        """Initialize the ContextSentenceCacher."""
        super(ContextSentenceCacher, self).__init__()
        logger.debug(f"Initialized '{self.identifier}'.")

    def _call(self, document_base: DocumentBase, interaction_callback: BaseInteractionCallback,
              status_callback: BaseStatusCallback, statistics: Statistics) -> None:
        nuggets: List[InformationNugget] = document_base.nuggets
        statistics["num_nuggets"] = len(nuggets)

        for nugget in nuggets:
            sent_start_chars: List[int] = nugget.document[SentenceStartCharsSignal]
            context_start_char: int = 0
            context_end_char: int = 0
            for ix, sent_start_char in enumerate(sent_start_chars):
                if sent_start_char > nugget.start_char:
                    if ix == 0:
                        context_start_char: int = 0
                        context_end_char: int = sent_start_char
                        statistics["num_context_sentence_before_first_sentence"] += 1
                        break
                    else:
                        context_start_char: int = sent_start_chars[ix - 1]
                        context_end_char: int = sent_start_char
                        statistics["num_context_sentence_is_first_or_inner_sentence"] += 1
                        break
            else:
                if sent_start_chars != []:
                    context_start_char: int = sent_start_chars[-1]
                    context_end_char: int = len(nugget.document.text)
                    statistics["num_context_sentence_is_final_sentence"] += 1

            context_sentence: str = nugget.document.text[context_start_char:context_end_char]
            start_in_context: int = nugget.start_char - context_start_char
            end_in_context: int = nugget.end_char - context_start_char

            nugget[CachedContextSentenceSignal] = CachedContextSentenceSignal({
                "text": context_sentence,
                "start_char": start_in_context,
                "end_char": end_in_context
            })

    def to_config(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier
        }

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "ContextSentenceCacher":
        return cls()


@register_configurable_element
class DuplicatedNuggetsCleaner(BasePipelineElement):
    """
    Removes duplicated nuggets.
    We consider a nugget duplicating another nugget if they belong to the same document, are located at the same
    position within the documents text and have "nearly" the same embedding. "Nearly" in this context refers to a
    tolerance value which is required while comparing two nugget embeddings as embedding values are represented as
    floats and therefore can't be compared for exact equality. For more details see
    :func`~wannadb.utils.embeddings_equal`
    """

    identifier: str = "DuplicatedNuggetsCleaner"

    required_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [TextEmbeddingSignal.identifier],
        "attributes": [],
        "documents": []
    }

    def __init__(self):
        """Initialize the DuplicatedNuggetsCleaner."""
        super(DuplicatedNuggetsCleaner, self).__init__()
        logger.debug(f"Initialized '{self.identifier}'.")

    def _call(self, document_base: DocumentBase, interaction_callback: BaseInteractionCallback,
              status_callback: BaseStatusCallback, statistics: Statistics) -> None:
        for document in document_base.documents:

            cleaned_nuggets: List[InformationNugget] = list()
            old_to_new_index: Dict[int, int] = dict()
            old_index = 0

            for nugget in document_base.nuggets:
                possible_duplicate, idx = get_possible_duplicate(nugget, document.nuggets)
                if possible_duplicate is None:
                    old_to_new_index[old_index] = len(cleaned_nuggets)
                    cleaned_nuggets.append(nugget)
                else:
                    old_to_new_index[old_index] = idx

                old_index += 1

            logger.info(f"Removed {len(document.nuggets) - len(cleaned_nuggets)} duplicated nuggets from document "
                        f"\"{document.name}\".")
            document.nuggets = cleaned_nuggets

            if CurrentMatchIndexSignal.identifier in document.signals:
                old_index = document[CurrentMatchIndexSignal].value
                document[CurrentMatchIndexSignal] = CurrentMatchIndexSignal(old_to_new_index[old_index])

    def to_config(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier
        }

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "DuplicatedNuggetsCleaner":
        return cls()

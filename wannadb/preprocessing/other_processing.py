import logging
from typing import Dict, List, Any

from wannadb.configuration import BasePipelineElement, register_configurable_element
from wannadb.data.data import DocumentBase, InformationNugget
from wannadb.data.signals import CachedContextSentenceSignal, \
    SentenceStartCharsSignal
from wannadb.interaction import BaseInteractionCallback
from wannadb.statistics import Statistics
from wannadb.status import BaseStatusCallback

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

import abc
import logging
import json
import os

from wannadb.data.data import Attribute, Document, DocumentBase, InformationNugget

logger: logging.Logger = logging.getLogger(__name__)
event_folder = "event_logs"
if not os.path.exists(event_folder):
    os.makedirs(event_folder)

class BaseEventLogger(abc.ABC):
    """
    Base class for event loggers that log events during the matching process.
    """
    
    identifier: str = "base_event_logger"


class MatchingEventLogger(BaseEventLogger):
    """
    Event logger that logs matching events.
    """
    
    identifier: str = "matching_event_logger"
    
    def __init__(self) -> None:
        """
        Initialize the MatchingEventLogger.
        """
        logger.debug("Initialized MatchingEventLogger.")
        
    def __call__(self, action: str, document_base: DocumentBase, attribute: Attribute, document: Document, nugget: InformationNugget, max_distance: float, not_a_match: InformationNugget = None) -> None:
        """
        Log a matching event.

        :param action: the action that triggered the event (e.g., "match", "no_match")
        :type action: str
        :param document_base: the document base associated with the event
        :type document_base: DocumentBase
        :param attribute: the attribute associated with the event
        :type attribute: Attribute
        :param document: the document associated with the event
        :type document: Document
        :param nugget: the information nugget associated with the event (if any)
        :type nugget: InformationNugget
        :param max_distance: the maximum distance used for matching (if applicable)
        :type max_distance: float
        :param not_a_match: the information nugget that was not a match (if applicable)
        :type not_a_match: InformationNugget
        """
        logger.info(f"Logging event: {action} for attribute '{attribute.name}' in document '{document.name}' with nugget '{nugget.text if nugget is not None else None}' and max distance {max_distance}.")
        if not os.path.exists(f"{event_folder}/{hash(document_base)}_history.jsonl"):
            with open(f"{event_folder}/{hash(document_base)}_history.jsonl", "w") as f:
                pass
        with open(f"{event_folder}/{hash(document_base)}_history.jsonl", "a") as f:
            event_record = {
                "action": action,
                "attribute": attribute.name,
                "document": document.name,
                "nugget": {
                    "start_char": nugget.start_char,
                    "end_char": nugget.end_char,
                    "text": nugget.text
                } if nugget is not None else None,
                "not_a_match": {
                        "start_char": not_a_match.start_char,
                        "end_char": not_a_match.end_char,
                        "text": not_a_match.text
                } if not_a_match is not None else None,
                "max_distance": max_distance
            }
            f.write(f"{json.dumps(event_record)}\n")
            
    def save_history_base(self, document_base: DocumentBase) -> None:
        """
        Save the document base associated with the history.

        :param document_base: the document base to save
        """
        with open(f"{event_folder}/{hash(document_base)}_history_document_base.bson", "wb") as f:
            f.write(document_base.to_bson(save_attribute_mappings=False))
        
        
class EmptyEventLogger(BaseEventLogger):
    """
    Event logger that does not log any events.
    """
    
    identifier: str = "empty_event_logger"
    
    def __call__(self, action: str, document_base: DocumentBase, attribute: Attribute, document: Document, nugget: InformationNugget, max_distance: float, not_a_match: InformationNugget = None) -> None:
        """
        Do nothing.

        :param event: event data to log
        """
        pass
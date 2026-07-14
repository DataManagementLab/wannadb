import abc
import json
import logging
from typing import Any, Dict, List, Tuple
from wannadb.data.data import DocumentBase, InformationNugget, MatchingEvent
from wannadb.event_logger import event_folder
from wannadb.interaction import BaseInteractionCallback, InteractionCallback
from wannadb.statistics import Statistics
from wannadb.status import BaseStatusCallback
from wannadb.matching.matching import RankingBasedMatcher, ReplayMatcher
from wannadb.matching.distance import BaseDistance
from wannadb.configuration import BasePipelineElement, Pipeline
from wannadb.matching.custom_match_extraction import BaseCustomMatchExtractor

logger: logging.Logger = logging.getLogger(__name__)

class BaseReplayer(BasePipelineElement, abc.ABC):
    """
    Base class for replayers that replay previous matching decisions.
    """
    identifier: str = "base_replayer"
    
    def _nugget_in_list_of_nuggets_ignore_signals(
            self,
            nugget: InformationNugget,
            nuggets: List[InformationNugget]
        ) -> bool:
        """
        Check if a nugget is in a list of nuggets, ignoring the signals of the nuggets.

        :param nugget: the nugget to check
        :param nuggets: the list of nuggets to check against
        :type nugget: InformationNugget
        :type nuggets: List[InformationNugget]
        :return: whether the nugget is in the list of nuggets, ignoring signals
        :rtype: bool
        """
        if nugget is None:
            return False
        for _nugget in nuggets:
            if (_nugget.text == nugget.text and
                _nugget.start_char == nugget.start_char and
                _nugget.end_char == nugget.end_char and
                _nugget.document == nugget.document):
                logger.warning(_nugget is nugget)
                return True
        return False
    
    def _get_complete_nugget_from_list(nugget: InformationNugget, nuggets: List[InformationNugget]) -> InformationNugget:
        """
        Get the complete nugget from a list of nuggets based on the text and position of the nugget, ignoring the signals of the nuggets.

        :param nugget: the nugget to get
        :param nuggets: the list of nuggets to get from
        :type nugget: InformationNugget
        :type nuggets: List[InformationNugget]
        :return: the complete nugget from the list of nuggets that matches the text and position of the given nugget, or None if no such nugget is found
        :rtype: InformationNugget
        """
        for _nugget in nuggets:
            if _nugget.text == nugget.text and _nugget.start_char == nugget.start_char and _nugget.end_char == nugget.end_char:
                return _nugget
        return None
    
class RankingBasedMatchingReplayer(BaseReplayer):
    """
    Replayer that replays previous matching decisions based on a ranking strategy.
    """
    identifier: str = "ranking_based_matching_replayer"
    
    def __init__(
            self,
            distance: BaseDistance,
            max_num_feedback: int,
            len_ranked_list: int,
            max_distance: float,
            num_random_docs: int,
            sampling_mode: str,
            adjust_threshold: bool,
            nugget_pipeline: Pipeline,
            find_additional_nuggets: BaseCustomMatchExtractor,
            num_bad_docs: int = 5,
            num_recent_docs: int = 5,
            store_best_guesses: bool = False,
    ) -> None:
        """
        Initialize the RankingBasedMatcher.

        :param distance: distance function
        :param max_num_feedback: maximum number of user interactions per attribute
        :param len_ranked_list: length of the ranked list of nuggets presented to the user for feedback
        :param max_distance: maximum distance at which nuggets will be accepted
        :param num_random_docs: number of random documents that are part of the ranked list of nuggets
        :param sampling_mode: determines how to sample the nuggets presented to the user for feedback
        :param adjust_threshold: whether to adjust the maximum distance threshold based on the user feedback
        :param nugget_pipeline: pipeline that is used to process newly-generated nuggets
        :param find_additional_nuggets: optional function to add nuggets similar to a manually added and matched nugget
        :param num_bad_docs: number of randomly selected documents without promising nuggets to be shown to the user
        :param num_recent_docs: number of documents that recently got interesting additional extractions to be shown to the user
        :param store_best_guesses: whether to store the best guesses for each feedback round
        """
        super(RankingBasedMatchingReplayer, self).__init__()
        self.matcher = ReplayMatcher(
            distance=distance,
            max_num_feedback=max_num_feedback,
            len_ranked_list=len_ranked_list,
            max_distance=max_distance,
            num_random_docs=num_random_docs,
            sampling_mode=sampling_mode,
            adjust_threshold=adjust_threshold,
            nugget_pipeline=nugget_pipeline,
            find_additional_nuggets=find_additional_nuggets,
            num_bad_docs=num_bad_docs,
            num_recent_docs=num_recent_docs,
            store_best_guesses=store_best_guesses
        )
        self.current_attribute = None
        self.enumerated_history: List[Tuple[int, MatchingEvent]] = []
        self.stack = []
        
        def replay_interaction_fn(pipeline_element_identifier: str, data: Dict[str, Any]) -> Dict[str, Any]:
            """
            Function to replay interactions based on the stored history. By loading the history of interactions for a document,
            this function can replay the interactions in the same order as they originally happened, allowing to reproduce the matching process and its decisions.
            This allows to revert tp previous states or revert single events by skipping them in the replay process.
            
            :param pipeline_element_identifier: identifier of the pipeline element that triggers the interaction
            :param data: data associated with the interaction
            :return: response to the interaction based on the stored history
            """
            if not "replay-event-request" in data.keys():
                return self._stop_matching()
            if len(self.stack) == 0:
                logger.warning(f"No more interactions in history for attribute '{self.current_attribute}'.")
                return self._stop_replay()
            _, next = self.stack.pop(0) if len(self.stack) > 0 else (None, None)
            if next is None:
                logger.warning(f"No more interactions in history for attribute '{self.current_attribute}' that match the nuggets in the current interaction data. Stopping replay.\nCurrent interaction data: {data}")
                return self._stop_replay()
            if next.nugget is None:
                logger.warning(f"Nugget in next interaction to replay is None. This should not happen, as the nugget is a required field for all interaction events in the history. Skipping this event.\nEvent data: {next.to_dict() if next else 'None'}")
                return self._stop_replay()
            if next.action == "is-match":
                return self._replay_match(next)
            elif next.action == "no-match-in-document":
                return self._replay_no_match_in_document(next)
            elif next.action == "custom-match":
                return self._replay_custom_match(next)
            elif next.action == "revert-event":
                return self._replay_revert_event(next)
            else:
                logger.warning(f"Unknown action '{next.action}' in interaction replay.\nAction will be skipped.")
                return {}
        
        self.interaction_callback: InteractionCallback = InteractionCallback(replay_interaction_fn)

        logger.debug(f"Initialized '{self.identifier}'.")
        
    def _call(
            self,
            document_base: DocumentBase,
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
        ) -> None:
        
        with open(f"{event_folder}/{hash(document_base)}_history.jsonl", "r") as f:
            history_lines = f.readlines()
        history = [MatchingEvent.from_dict(json.loads(line), document_base) for line in history_lines]
        self.enumerated_history: List[Tuple[int, MatchingEvent]] = list(enumerate(history))
        
        # collect events to skip
        ids_to_skip = set(event.revert_event_id for idx, event in self.enumerated_history if event.action == "revert-event")
        self.enumerated_history = list(filter(lambda x: x[0] not in ids_to_skip, self.enumerated_history))
        self.stack = self.enumerated_history.copy()
        
        self.matcher(
            document_base=document_base,
            interaction_callback=self.interaction_callback,
            status_callback=status_callback,
            statistics=statistics
        )
            
    def _replay_match(
            self,
            event: MatchingEvent
        ) -> None:
        """
        Replay matching decisions based on the stored history.

        :param event: the matching event to replay
        :type event: MatchingEvent
        """
        return {
            "message": "replay-next-event",
            "action": "is-match",
            "nugget": event.nugget,
            "not-a-match": event.not_a_match,
            "attribute": event.attribute
        }
    
    def _replay_no_match_in_document(
            self,
            event: MatchingEvent
        ) -> None:
        """
        Replay a no-match-in-document decision.

        :param event: the no-match-in-document event to replay
        :type event: MatchingEvent
        """
        return {
            "message": "replay-next-event",
            "action": "no-match-in-document",
            "nugget": event.nugget,
            "not-a-match": event.not_a_match,
            "attribute": event.attribute,
            "document": event.document
        }
    
    def _replay_custom_match(
            self,
            event: MatchingEvent,
            custom_nuggets_saved_in_history: bool = True
        ) -> None:
        """
        Replay custom match extraction based on the stored history.
        
        :param event: the custom match event to replay
        :type event: MatchingEvent
        :param custom_nuggets_saved_in_history: whether the custom nuggets are saved in the history (if false, the replay will only return the position of the nugget in the document, but not the nugget itself, to allow replaying even if the custom nuggets are not saved in the history)
        :type custom_nuggets_saved_in_history: bool
        :return: response to the custom match event based on the stored history
        :rtype: Dict[str, Any]
        """
        if not custom_nuggets_saved_in_history:
            return {
                "message": "replay-next-event",
                "action": "custom-match",
                "document": event.document.name,
                "start": event.nugget.start_char,
                "end": event.nugget.end_char,
                "attribute": event.attribute
            }
        return {
            "message": "replay-next-event",
            "action": "is-match",
            "nugget": event.nugget,
            "not-a-match": event.not_a_match,
            "attribute": event.attribute
        }
        
    def _replay_revert_event(
            self,
            event: MatchingEvent
        ) -> None:
        """
        Replay a revert event based on the stored history.
        :param event: the revert event to replay
        :type event: MatchingEvent
        """
        # event already skipped in the replay process by filtering the enumerated history based on the revert_event_id of the events to skip
        pass
    
    def _stop_replay(self) -> None:
        """
        Stop the replay process.
        """
        return {"message": "stop-replay"}
    
    def _stop_matching(self) -> None:
        """
        Stop the matching process.
        """
        return {"message": "stop-interactive-matching"}
    
    def to_config(self) -> Dict[str, Any]:
        """
        Get the configuration of the replayer as a dictionary.

        :return: configuration of the replayer
        :rtype: Dict[str, Any]
        """
        return {
            "identifier": self.identifier,
            "distance": self.matcher.distance.to_config(),
            "max_num_feedback": self.matcher.max_num_feedback,
            "len_ranked_list": self.matcher.len_ranked_list,
            "max_distance": self.matcher.max_distance,
            "num_random_docs": self.matcher.num_random_docs,
            "sampling_mode": self.matcher.sampling_mode,
            "adjust_threshold": self.matcher.adjust_threshold,
            "nugget_pipeline": self.matcher.nugget_pipeline.to_config(),
            "find_additional_nuggets": self.matcher.find_additional_nuggets.to_config() if self.matcher.find_additional_nuggets else None,
            "num_bad_docs": self.matcher.num_bad_docs,
            "num_recent_docs": self.matcher.num_recent_docs,
            "store_best_guesses": self.matcher.store_best_guesses
        }
        
    def revert_event(self, document_base: DocumentBase, event_id: int, corrected_decision: Dict[str, Any]) -> None:
        """
        Revert a matching event by its ID. The event will be skipped in the replay process, effectively reverting its effect on the matching decisions.

        :param document_base: the document base associated with the event to revert
        :type document_base: DocumentBase
        :param event_id: the ID of the event to revert
        :type event_id: int
        :param corrected_decision: the corrected decision for the event
        :type corrected_decision: Dict[str, Any]
        """
        with open(f"{event_folder}/{hash(document_base)}_history.jsonl", "a") as f:
            revert_event = MatchingEvent(
                action="revert-event",
                attribute=corrected_decision.get("attribute"),
                document=corrected_decision.get("document"),
                nugget=corrected_decision.get("nugget"),
                not_a_match=corrected_decision.get("not-a-match"),
                max_distance=corrected_decision.get("max_distance", 0.0),
                correct_action=corrected_decision.get("action"),
                revert_event_id=event_id
            )
            f.write(json.dumps(revert_event.to_dict()) + "\n")
            
import abc
import logging
import random
import time
from typing import Any, Dict, List, Callable, Tuple

import numpy as np

from wannadb.configuration import BasePipelineElement, register_configurable_element, Pipeline
from wannadb.data.data import Document, DocumentBase, InformationNugget
from wannadb.data.signals import CachedContextSentenceSignal, CachedDistanceSignal, \
    SentenceStartCharsSignal, CurrentMatchIndexSignal, LabelSignal
from wannadb.interaction import BaseInteractionCallback
from wannadb.matching.custom_match_extraction import BaseCustomMatchExtractor
from wannadb.matching.distance import BaseDistance
from wannadb.statistics import Statistics
from wannadb.status import BaseStatusCallback

logger: logging.Logger = logging.getLogger(__name__)


class BaseMatcher(BasePipelineElement, abc.ABC):
    """
    Base class for all matchers.

    A matcher attempts to find matching InformationNuggets for the Attributes.
    """
    identifier: str = "BaseMatcher"


########################################################################################################################
# actual matchers
########################################################################################################################


@register_configurable_element
class RankingBasedMatcher(BaseMatcher):
    """Matcher that displays a ranked list of nuggets to the user for feedback."""

    identifier: str = "RankingBasedMatcher"

    required_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [CachedContextSentenceSignal.identifier],
        "attributes": [],
        "documents": [SentenceStartCharsSignal.identifier]
    }

    generated_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [
            CachedDistanceSignal.identifier,
        ],
        "attributes": [],
        "documents": []
    }

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
        """
        super(RankingBasedMatcher, self).__init__()
        self._distance: BaseDistance = distance
        self._max_num_feedback: int = max_num_feedback
        self._len_ranked_list: int = len_ranked_list
        self._default_max_distance: float = max_distance
        self._max_distance: float = max_distance
        self._num_random_docs: int = num_random_docs
        self._sampling_mode: str = sampling_mode
        self._adjust_threshold: bool = adjust_threshold
        self._nugget_pipeline: Pipeline = nugget_pipeline
        self._find_additional_nuggets = find_additional_nuggets

        # add signals required by the distance function to the signals required by the matcher
        self._add_required_signal_identifiers(self._distance.required_signal_identifiers)

        logger.debug(f"Initialized '{self.identifier}'.")

    def _call(
            self,
            document_base: DocumentBase,
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        statistics["num_documents"] = len(document_base.documents)
        statistics["num_nuggets"] = len(document_base.nuggets)

        for attribute in document_base.attributes:
            feedback_result: Dict[str, Any] = interaction_callback(
                self.identifier,
                {
                    "do-attribute-request": None,
                    "attribute": attribute
                }
            )

            if not feedback_result["do-attribute"]:
                logger.info(f"Skip attribute '{attribute.name}'.")
                statistics[attribute.name]["skipped"] = True
                continue

            logger.info(f"Matching attribute '{attribute.name}'.")
            self._max_distance = self._default_max_distance
            statistics[attribute.name]["max_distances"] = [self._max_distance]
            statistics[attribute.name]["feedback_durations"] = []

            if any((attribute.name in document.attribute_mappings.keys() for document in document_base.documents)):
                logger.info(f"Attribute '{attribute.name}' has already been matched before.")
                continue

            remaining_documents: List[Document] = []

            # compute initial distances as distances to label
            logger.info("Compute initial distances and initialize documents.")
            tik: float = time.time()

            distances: np.ndarray = self._distance.compute_distances(
                [attribute], document_base.nuggets, statistics["distance"]
            )[0]
            for nugget, distance in zip(document_base.nuggets, distances):
                nugget[CachedDistanceSignal] = CachedDistanceSignal(distance)
            distances_based_on_label: bool = True

            for document in document_base.documents:
                try:
                    index, _ = min(enumerate(document.nuggets), key=lambda nugget: nugget[1][CachedDistanceSignal])
                except ValueError:  # document has no nuggets
                    document.attribute_mappings[attribute.name] = []
                    statistics[attribute.name]["num_document_with_no_nuggets"] += 1
                else:
                    document[CurrentMatchIndexSignal] = CurrentMatchIndexSignal(index)
                    remaining_documents.append(document)

            tak: float = time.time()
            logger.info(f"Computed initial distances and initialized documents in {tak - tik} seconds.")

            # iterative user interactions
            logger.info("Execute interactive matching.")
            tik: float = time.time()
            num_feedback: int = 0
            continue_matching: bool = True
            while continue_matching and num_feedback < self._max_num_feedback and remaining_documents != []:
                # sort remaining documents by distance
                remaining_documents = list(sorted(
                    remaining_documents,
                    key=lambda x: x.nuggets[x[CurrentMatchIndexSignal]][CachedDistanceSignal],
                    reverse=True
                ))

                if self._sampling_mode == "MOST_UNCERTAIN":
                    selected_documents: List[Document] = remaining_documents[:self._len_ranked_list]

                    num_nuggets_above: int = 0
                    num_nuggets_below: int = len(remaining_documents) - self._len_ranked_list
                elif self._sampling_mode == "MOST_UNCERTAIN_WITH_RANDOMS":
                    # sample random documents and move them to the front of the ranked list
                    random_documents: List[Document] = []
                    for i in range(self._num_random_docs):
                        if remaining_documents != []:
                            random_document: Document = random.choice(remaining_documents)
                            random_documents.append(random_document)
                            remaining_documents.remove(random_document)

                    remaining_documents: List[Document] = random_documents + remaining_documents
                    selected_documents = remaining_documents[:self._len_ranked_list]

                    num_nuggets_above: int = 0
                    num_nuggets_below: int = len(remaining_documents) - self._len_ranked_list
                elif self._sampling_mode == "AT_MAX_DISTANCE_THRESHOLD":
                    ix_lower: int = 0
                    while ix_lower < len(remaining_documents) and \
                            remaining_documents[ix_lower].nuggets[
                                remaining_documents[ix_lower][CurrentMatchIndexSignal]][
                                CachedDistanceSignal] > self._max_distance:
                        ix_lower += 1

                    higher_left: int = max(0, ix_lower - self._len_ranked_list // 2)
                    higher_right: int = ix_lower
                    higher_num: int = higher_right - higher_left
                    lower_left: int = ix_lower
                    lower_right: int = min(len(remaining_documents), ix_lower + self._len_ranked_list // 2)
                    lower_num: int = lower_right - lower_left

                    if lower_num < self._len_ranked_list // 2:
                        higher_left = max(0, higher_left - (self._len_ranked_list // 2 - lower_num))
                    elif higher_num < self._len_ranked_list // 2:
                        lower_right = min(len(remaining_documents),
                                          lower_right + (self._len_ranked_list // 2 - higher_num))

                    selected_documents: List[Document] = remaining_documents[higher_left:lower_right]

                    num_nuggets_above: int = higher_left
                    num_nuggets_below: int = len(remaining_documents) - lower_right
                else:
                    logger.error(f"Unknown sampling mode '{self._sampling_mode}'!")
                    assert False, f"Unknown sampling mode '{self._sampling_mode}'!"

                # present documents to the user for feedback
                feedback_nuggets, feedback_nuggets_old_cached_distances = zip(
                    *(
                        (feedback_nugget, feedback_nugget[CachedDistanceSignal]) for feedback_nugget in
                        (
                            doc.nuggets[doc[CurrentMatchIndexSignal]] for doc in selected_documents)
                    )
                )
                num_feedback += 1
                statistics[attribute.name]["num_feedback"] += 1
                t0 = time.time()
                feedback_result: Dict[str, Any] = interaction_callback(
                    self.identifier,
                    {
                        "max-distance": self._max_distance,
                        "nuggets": feedback_nuggets,
                        "attribute": attribute,
                        "num-feedback": num_feedback,
                        "num-nuggets-above": num_nuggets_above,
                        "num-nuggets-below": num_nuggets_below
                    }
                )
                t1 = time.time()
                statistics[attribute.name]["feedback_durations"].append(t1 - t0)

                if feedback_result["message"] == "stop-interactive-matching":
                    statistics[attribute.name]["stopped_matching_by_hand"] = True
                    continue_matching = False
                elif feedback_result["message"] == "no-match-in-document":
                    statistics[attribute.name]["num_no_match_in_document"] += 1
                    feedback_result["nugget"].document.attribute_mappings[attribute.name] = []
                    remaining_documents.remove(feedback_result["nugget"].document)

                    if self._adjust_threshold:
                        # threshold adjustment: if the given nugget's cached distance is smaller than the threshold,
                        # update the threshold to the minimum cached distance of all nuggets that are above in the
                        # ranked list, but were below the threshold before
                        if feedback_result["nugget"][CachedDistanceSignal] < self._max_distance:
                            nugget_ix = -1
                            for ix, nugget in enumerate(feedback_nuggets):
                                if nugget is feedback_result["nugget"]:
                                    nugget_ix = ix
                                    break
                            assert nugget_ix != -1

                            if nugget_ix > 0:
                                min_dist = 1
                                for ix in range(nugget_ix):
                                    if feedback_nuggets_old_cached_distances[ix] < self._max_distance:
                                        min_dist = min(min_dist, feedback_nuggets[ix][CachedDistanceSignal])
                                if min_dist < self._max_distance:
                                    self._max_distance = min_dist
                                    statistics[attribute.name]["max_distances"].append(min_dist)
                                    logger.info(f"NO MATCH IN DOCUMENT: Decreased the maximum distance to "
                                                f"{self._max_distance}.")
                                else:
                                    logger.info("NO MATCH IN DOCUMENT: Did not change the maximum distance since it "
                                                "would not be decreased.")
                            else:
                                logger.info("NO MATCH IN DOCUMENT: Did not change the maximum distance since the "
                                            "document is at the top of the list.")
                        else:
                            logger.info("NO MATCH IN DOCUMENT: Did not change the maximum distance since the document"
                                        "was already above the old threshold.")

                elif feedback_result["message"] == "custom-match":
                    statistics[attribute.name]["num_custom_match"] += 1

                    def run_nugget_pipeline(nuggets):
                        # run the nugget pipeline for this nugget
                        dummy_documents = []
                        for n in nuggets:
                            dummy_document = Document("dummy", n.document.text)
                            dummy_document[SentenceStartCharsSignal] = n.document[SentenceStartCharsSignal]
                            dummy_document.nuggets.append(n)
                            # TODO: think about other signals that might be required
                            dummy_documents.append(dummy_document)

                        dummy_document_base = DocumentBase(dummy_documents, [])
                        self._nugget_pipeline(dummy_document_base, interaction_callback, status_callback, statistics["nugget-pipeline"])

                    statistics[attribute.name]["num_confirmed_match"] += 1

                    confirmed_nugget = InformationNugget(feedback_result["document"], feedback_result["start"], feedback_result["end"])
                    confirmed_nugget[LabelSignal] = attribute.name

                    run_nugget_pipeline([confirmed_nugget])

                    # add other signals for this nugget
                    confirmed_nugget[CachedDistanceSignal] = CachedDistanceSignal(0.0)
                    # TODO: think about other signals that should be added

                    # add this nugget to the document as a match and remove the document from remaining documents
                    feedback_result["document"].nuggets.append(confirmed_nugget)
                    feedback_result["document"].attribute_mappings[attribute.name] = [confirmed_nugget]
                    remaining_documents.remove(feedback_result["document"])

                    # update the distances for the other documents
                    for document in remaining_documents:
                        new_distances: np.ndarray = self._distance.compute_distances(
                            [confirmed_nugget],
                            document.nuggets,
                            statistics["distance"]
                        )[0]
                        for nugget, new_distance in zip(document.nuggets, new_distances):
                            if distances_based_on_label or new_distance < nugget[CachedDistanceSignal]:
                                nugget[CachedDistanceSignal] = new_distance
                        for ix, nugget in enumerate(document.nuggets):
                            current_guess: InformationNugget = document.nuggets[document[CurrentMatchIndexSignal]]
                            if nugget[CachedDistanceSignal] < current_guess[CachedDistanceSignal]:
                                document[CurrentMatchIndexSignal] = ix
                    distances_based_on_label = False

                    # Find more nuggets that are similar to this match
                    t_minus_custom_extraction = time.time()
                    additional_nuggets: List[Tuple[Document, int, int]] = self._find_additional_nuggets(confirmed_nugget, remaining_documents)
                    t_custom_extraction = time.time() - t_minus_custom_extraction

                    # Perform time keeping and logging
                    self._find_additional_nuggets.perform_time_keeping(
                        feedback_result["document"],
                        len(remaining_documents),
                        t_custom_extraction,
                        feedback_result["start"],
                        feedback_result["end"]
                    )
                    logger.info(f"Execution of custom match extraction"
                                f" with {str(self._find_additional_nuggets)}"
                                f" took {t_custom_extraction} seconds"
                                f" for {len(remaining_documents)} documents.")

                    statistics[attribute.name]["num_additional_nuggets"] += len(additional_nuggets)
                    if len(additional_nuggets) == 0:
                        continue

                    # convert nugget description into InformationNugget
                    additional_nuggets = list(map(lambda i: InformationNugget(*i), additional_nuggets))
                    for additional_nugget in additional_nuggets:
                        additional_nugget[LabelSignal] = attribute.name
                        additional_nugget.document.nuggets.append(additional_nugget)
                    run_nugget_pipeline(additional_nuggets)

                    # TODO: maybe there is a better way than to compute distances based on currently confirmed nugget?
                    # calculate proper distances based on currently confirmed nugget
                    new_distances: np.ndarray = self._distance.compute_distances(
                        [confirmed_nugget],
                        additional_nuggets,
                        statistics["distance"]
                    )[0]
                    for nugget, new_distance in zip(additional_nuggets, new_distances):
                        nugget[CachedDistanceSignal] = new_distance
                    for nugget in additional_nuggets:
                        current_guess: InformationNugget = nugget.document.nuggets[nugget.document[CurrentMatchIndexSignal]]
                        if nugget[CachedDistanceSignal] < current_guess[CachedDistanceSignal]:
                            nugget.document[CurrentMatchIndexSignal] = nugget.document.nuggets.index(nugget)

                elif feedback_result["message"] == "is-match":
                    statistics[attribute.name]["num_confirmed_match"] += 1
                    feedback_result["nugget"].document.attribute_mappings[attribute.name] = [feedback_result["nugget"]]
                    remaining_documents.remove(feedback_result["nugget"].document)

                    # update the distances for the other documents
                    for document in remaining_documents:
                        new_distances: np.ndarray = self._distance.compute_distances(
                            [feedback_result["nugget"]],
                            document.nuggets,
                            statistics["distance"]
                        )[0]
                        for nugget, new_distance in zip(document.nuggets, new_distances):
                            if distances_based_on_label or new_distance < nugget[CachedDistanceSignal]:
                                nugget[CachedDistanceSignal] = new_distance
                        for ix, nugget in enumerate(document.nuggets):
                            current_guess: InformationNugget = document.nuggets[document[CurrentMatchIndexSignal]]
                            if nugget[CachedDistanceSignal] < current_guess[CachedDistanceSignal]:
                                document[CurrentMatchIndexSignal] = ix
                    distances_based_on_label = False

                    if self._adjust_threshold:
                        # threshold adjustment: if the confirmed nugget's distance is larger than the threshold, update
                        # the threshold to the maximum cached distance of all nuggets that are below in the ranked list,
                        # but were above the threshold before
                        if feedback_result["not-a-match"] is None:  # nugget from original list confirmed
                            if feedback_result["nugget"][CachedDistanceSignal] > self._max_distance:
                                nugget_ix = -1
                                for ix, nugget in enumerate(feedback_nuggets):
                                    if nugget is feedback_result["nugget"]:
                                        nugget_ix = ix
                                        break
                                assert nugget_ix != -1

                                if nugget_ix < len(feedback_nuggets) - 1:
                                    max_dist = 0
                                    for ix in range(nugget_ix + 1, len(feedback_nuggets)):
                                        if feedback_nuggets_old_cached_distances[ix] > self._max_distance:
                                            max_dist = max(max_dist, feedback_nuggets[ix][CachedDistanceSignal])
                                    if max_dist > self._max_distance:
                                        self._max_distance = max_dist
                                        statistics[attribute.name]["max_distances"].append(max_dist)
                                        logger.info(f"CONFIRMED NUGGET FROM RANKED LIST: Increased the maximum distance"
                                                    f"to {self._max_distance}.")
                                    else:
                                        logger.info("CONFIRMED NUGGET FROM RANKED LIST: Did not change the maximum "
                                                    "distance since it would not be increased.")
                                else:
                                    logger.info("CONFIRMED NUGGET FROM RANKED LIST: Did not change the maximum "
                                                "distance since the confirmed nugget is at the bottom of the list.")
                            else:
                                logger.info("CONFIRMED NUGGET FROM RANKED LIST: Did not change the maximum distance "
                                            "since the document was already below the old threshold.")
                        else:
                            logger.info("CONFIRMED NUGGET NOT IN RANKED LIST: Did not change the maximum distance "
                                        "since the confirmed nugget was not in the ranked list.")

            tak: float = time.time()
            logger.info(f"Executed interactive matching in {tak - tik} seconds.")

            # update remaining documents
            logger.info("Update remaining documents.")
            tik: float = time.time()

            for document in remaining_documents:
                current_guess: InformationNugget = document.nuggets[document[CurrentMatchIndexSignal]]
                if current_guess[CachedDistanceSignal] < self._max_distance:
                    statistics[attribute.name]["num_guessed_match"] += 1
                    document.attribute_mappings[attribute.name] = [current_guess]
                else:
                    statistics[attribute.name]["num_blocked_by_max_distance"] += 1
                    document.attribute_mappings[attribute.name] = []

            tak: float = time.time()
            logger.info(f"Updated remaining documents in {tak - tik} seconds.")

    def to_config(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier,
            "distance": self._distance.to_config(),
            "max_num_feedback": self._max_num_feedback,
            "len_ranked_list": self._len_ranked_list,
            "max_distance": self._max_distance,
            "num_random_docs": self._num_random_docs,
            "sampling_mode": self._sampling_mode,
            "adjust_threshold": self._adjust_threshold,
            "nugget_pipeline": self._nugget_pipeline.to_config()
        }

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "RankingBasedMatcher":
        distance: BaseDistance = BaseDistance.from_config(config["distance"])
        return cls(distance, config["max_num_feedback"], config["len_ranked_list"], config["max_distance"],
                   config["num_random_docs"], config["sampling_mode"], config["adjust_threshold"],
                   Pipeline.from_config(config["nugget_pipeline"]))

import abc
import logging
import random
import time
from typing import Any, Dict, List, Tuple, Counter, Optional

import numpy as np

from wannadb.configuration import BasePipelineElement, register_configurable_element, Pipeline
from wannadb.data.data import Document, DocumentBase, InformationNugget
from wannadb.data.signals import CachedContextSentenceSignal, CachedDistanceSignal, \
    SentenceStartCharsSignal, CurrentMatchIndexSignal, LabelSignal, ExtractorNameSignal, CurrentThresholdSignal
from wannadb.interaction import BaseInteractionCallback
from wannadb.matching.custom_match_extraction import BaseCustomMatchExtractor
from wannadb.matching.distance import BaseDistance
from wannadb.models import NewlyAddedNuggetContext, NuggetUpdatesContext, BestMatchUpdate, ThresholdPositionUpdate
from wannadb.statistics import Statistics
from wannadb.status import BaseStatusCallback
from wannadb_ui.common import AddedReason, ThresholdPosition

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
        self.num_bad_docs = num_bad_docs
        self.num_recent_docs = num_recent_docs
        self.store_best_guesses = store_best_guesses

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
            start_matching: float = time.time()
            self._max_distance = self._default_max_distance
            self._old_max_distance = -1
            attribute[CurrentThresholdSignal] = CurrentThresholdSignal(self._max_distance)
            statistics[attribute.name]["max_distances"] = [self._max_distance]
            statistics[attribute.name]["feedback_durations"] = []
            if self.store_best_guesses:
                statistics[attribute.name]["best_guesses"] = []

            if any((attribute.name in document.attribute_mappings.keys() for document in document_base.documents)):
                logger.info(f"Attribute '{attribute.name}' has already been matched before.")
                continue

            remaining_documents: List[Document] = []
            docs_with_added_nuggets: Counter[Document] = Counter()

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
                    remaining_documents.append(document) # TODO Change handling of remaining documents list to allow adding even docs without nuggets (as they might be found by generalization)
            logger.info(f"{len(remaining_documents)} documents to fill.")

            tak: float = time.time()
            logger.info(f"Computed initial distances and initialized documents in {tak - tik} seconds.")

            def _sort_remaining_documents():
                remaining_documents.sort(
                    key=lambda x: x.nuggets[x[CurrentMatchIndexSignal]][CachedDistanceSignal],
                    reverse=True
                )

            # iterative user interactions
            logger.info("Execute interactive matching.")
            tik: float = time.time()
            self._old_feedback_nuggets: List[InformationNugget] = []
            self._new_nugget_contexts: List[NewlyAddedNuggetContext] = []
            num_feedback: int = 0
            continue_matching: bool = True
            new_best_matches: Counter[str] = Counter[str]()
            new_to_old_match: Dict[str, str] = {}
            old_distances: Dict[InformationNugget, float] = {}
            while continue_matching and num_feedback < self._max_num_feedback and remaining_documents != []:
                # sort remaining documents by distance
                _sort_remaining_documents()

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

                    selected_documents: List[Document] = []

                    num_nuggets_above: int = higher_left
                    num_nuggets_below: int = len(remaining_documents) - lower_right
                    selected_docs_with_added_nuggets = set()

                    # Add additional documents (most uncertain)...
                    if self.num_bad_docs > 0 and num_nuggets_above > 0:
                        k = min(self.num_bad_docs, num_nuggets_above)
                        new_docs = random.choices(remaining_documents[:num_nuggets_above], k=k)
                        selected_documents.extend(new_docs)
                        num_nuggets_above -= k
                        self._update_new_nugget_contexts(new_docs, AddedReason.MOST_UNCERTAIN, old_distances)
                    # ...  and those that recently got interesting additional extractions to the list
                    if self.num_recent_docs > 0 and len(docs_with_added_nuggets) > 0:
                        # Create a list up to double the size wanted and then sample from that instead of only taking the same most promising documents potentially over and over again
                        selected_docs_with_added_nuggets = [d for d, _ in docs_with_added_nuggets.most_common(self.num_recent_docs * 2)] #random.choices(list(docs_with_added_nuggets), k=k)
                        if len(selected_docs_with_added_nuggets) > self.num_recent_docs:
                            selected_docs_with_added_nuggets = random.choices(selected_docs_with_added_nuggets, k=self.num_recent_docs)
                        selected_documents.extend(selected_docs_with_added_nuggets)
                        self._update_new_nugget_contexts(selected_docs_with_added_nuggets,
                                                         AddedReason.INTERESTING_ADDITIONAL_EXTRACTION,
                                                         old_distances)
                    selected_docs_with_added_nuggets = set(selected_docs_with_added_nuggets)

                    # Now fill the list with documents at threshold
                    docs_at_threshold_to_add = [doc for doc in remaining_documents[higher_left:lower_right] if
                                                doc not in selected_docs_with_added_nuggets]
                    selected_documents.extend(docs_at_threshold_to_add)
                    self._update_new_nugget_contexts(docs_at_threshold_to_add, AddedReason.AT_THRESHOLD, old_distances)

                    # Sort to unify the order across the different three sources
                    selected_documents.sort(key=lambda x: x.nuggets[x[CurrentMatchIndexSignal]][CachedDistanceSignal], reverse=True)
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
                all_guessed_nugget_matches = tuple([doc.nuggets[doc[CurrentMatchIndexSignal]] for doc in document_base.documents])
                num_feedback += 1
                statistics[attribute.name]["num_feedback"] += 1

                t0 = time.time()

                best_match_updates = [BestMatchUpdate(new_to_old_match[new_best_match],
                                                      new_best_match,
                                                      new_best_matches[new_best_match])
                                      for new_best_match in new_best_matches.keys()]
                threshold_position_updates = self._compute_threshold_position_updates(document_base, old_distances)
                nugget_updates_context = NuggetUpdatesContext(newly_added_nugget_contexts=self._new_nugget_contexts,
                                                              best_match_updates=best_match_updates,
                                                              threshold_position_updates=threshold_position_updates)

                feedback_result: Dict[str, Any] = interaction_callback(
                    self.identifier,
                    {
                        "max-distance": self._max_distance,
                        "max-distance-change": self._max_distance - self._old_max_distance if self._old_max_distance != -1 else 0,
                        "nuggets": feedback_nuggets,
                        "nugget-updates-context": nugget_updates_context,
                        "all-guessed-nugget-matches": all_guessed_nugget_matches,
                        "attribute": attribute,
                        "num-feedback": num_feedback,
                        "num-nuggets-above": num_nuggets_above,
                        "num-nuggets-below": num_nuggets_below,
                        "sampling-mode": self._sampling_mode
                    }
                )
                t1 = time.time()
                statistics[attribute.name]["feedback_durations"].append(t1 - t0)

                self._old_max_distance = self._max_distance
                self._old_feedback_nuggets = feedback_nuggets
                self._new_nugget_contexts.clear()
                old_distances = {nugget: nugget[CachedDistanceSignal] for nugget in document_base.nuggets}
                new_best_matches.clear()
                new_to_old_match.clear()

                if feedback_result["message"] == "stop-interactive-matching":
                    statistics[attribute.name]["stopped_matching_by_hand"] = True
                    continue_matching = False
                elif feedback_result["message"] == "no-match-in-document":
                    statistics[attribute.name]["num_no_match_in_document"] += 1
                    d = feedback_result["nugget"].document
                    if d in remaining_documents:
                        remaining_documents.remove(d)
                    else:
                        logger.warning(f"Trying to remove document {feedback_result['nugget'].document} from remaining documents, but it was already removed before. {len(remaining_documents)} remaining documents: {', '.join(d.name for d in remaining_documents)}")
                    if d in docs_with_added_nuggets:
                        docs_with_added_nuggets.pop(d)
                    feedback_result["nugget"].document.attribute_mappings[attribute.name] = []

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
                                    self._old_max_distance = self._max_distance
                                    self._max_distance = min_dist
                                    attribute[CurrentThresholdSignal] = CurrentThresholdSignal(min_dist)
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
                    logger.info(f"Custom match: '{confirmed_nugget}'")
                    confirmed_nugget[ExtractorNameSignal] = "<CUSTOM_SELECTION>"
                    confirmed_nugget[LabelSignal] = attribute.name

                    run_nugget_pipeline([confirmed_nugget])

                    # add other signals for this nugget
                    confirmed_nugget[CachedDistanceSignal] = CachedDistanceSignal(0.0)
                    # TODO: think about other signals that should be added

                    # add this nugget to the document as a match and remove the document from remaining documents
                    feedback_result["document"].nuggets.append(confirmed_nugget)
                    feedback_result["document"].attribute_mappings[attribute.name] = [confirmed_nugget]
                    remaining_documents.remove(feedback_result["document"])

                    # add this nugget as a confirmed match to the corresponding attribute
                    attribute.confirmed_matches.append(confirmed_nugget)

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

                        previous_best_match: InformationNugget = document.nuggets[document[CachedDistanceSignal]]
                        for ix, nugget in enumerate(document.nuggets):
                            current_guess: InformationNugget = document.nuggets[document[CurrentMatchIndexSignal]]
                            if nugget[CachedDistanceSignal] < current_guess[CachedDistanceSignal]:
                                document[CurrentMatchIndexSignal] = ix
                        new_best_match: InformationNugget = document.nuggets[document[CurrentMatchIndexSignal]]
                        if previous_best_match != new_best_match:
                            new_best_matches.update([new_best_match.text])
                            new_to_old_match[new_best_match.text] = previous_best_match.text

                    distances_based_on_label = False

                    # Find more nuggets that are similar to this match
                    t_minus_custom_extraction = time.time()
                    _sort_remaining_documents()
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
                    if len(additional_nuggets) > 0:
                        logger.info(f"Found {len(additional_nuggets)} additional nuggets.")
                        # convert nugget description into InformationNugget
                        additional_nuggets = list(map(lambda i: InformationNugget(*i), additional_nuggets))
                        for additional_nugget in additional_nuggets:
                            additional_nugget[LabelSignal] = attribute.name
                            additional_nugget[ExtractorNameSignal] = str(self._find_additional_nuggets)
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
                            # Calculate whether this new nugget is potentiall useful
                            # (has a distance lower than the current best guess for its document)
                            distance_difference = current_guess[CachedDistanceSignal] - nugget[CachedDistanceSignal]
                            if distance_difference > 0:
                                # Replace current guess with new nugget
                                nugget.document[CurrentMatchIndexSignal] = nugget.document.nuggets.index(nugget)
                                docs_with_added_nuggets[nugget.document] = distance_difference
                                logger.info(f"Found nugget better than current best guess for document {nugget.document.name} with distance difference {distance_difference}.")

                elif feedback_result["message"] == "is-match":
                    statistics[attribute.name]["num_confirmed_match"] += 1
                    feedback_result["nugget"].document.attribute_mappings[attribute.name] = [feedback_result["nugget"]]
                    doc = feedback_result["nugget"].document
                    try:
                        for d in remaining_documents:
                            if d.name == doc.name:
                                remaining_documents.remove(d)
                                break
                        #remaining_documents.remove(doc)
                    except ValueError:
                        logger.warning(f"Trying to remove document {doc.name} from remaining documents, but it was already removed before. {len(remaining_documents)} remaining documents: {', '.join(d.name for d in remaining_documents)}.")
                    if doc in docs_with_added_nuggets:
                        docs_with_added_nuggets.pop(doc)

                    # add this nugget as a confirmed match to the corresponding attribute
                    attribute.confirmed_matches.append(feedback_result["nugget"])

                    # update the distances for the other documents
                    for document in remaining_documents:
                        new_distances: np.ndarray = self._distance.compute_distances(
                            [feedback_result["nugget"]],
                            document.nuggets,
                            statistics["distance"]
                        ) [0]
                        for nugget, new_distance in zip(document.nuggets, new_distances):
                            if distances_based_on_label or new_distance < nugget[CachedDistanceSignal]:
                                nugget[CachedDistanceSignal] = new_distance

                        previous_best_match: InformationNugget = document.nuggets[document[CurrentMatchIndexSignal]]
                        for ix, nugget in enumerate(document.nuggets):
                            current_guess: InformationNugget = document.nuggets[document[CurrentMatchIndexSignal]]
                            if nugget[CachedDistanceSignal] < current_guess[CachedDistanceSignal]:
                                document[CurrentMatchIndexSignal] = ix
                        new_best_match: InformationNugget = document.nuggets[document[CurrentMatchIndexSignal]]
                        if previous_best_match != new_best_match:
                            new_best_matches.update([new_best_match.text])
                            new_to_old_match[new_best_match.text] = previous_best_match.text
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
                                        self._old_max_distance = self._max_distance
                                        self._max_distance = max_dist
                                        attribute[CurrentThresholdSignal] = CurrentThresholdSignal(max_dist)
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

                if self.store_best_guesses: # and (num_feedback == 0 or (num_feedback+1) % 5 == 0):
                    best_guesses = []
                    for document in document_base.documents:
                        if attribute.name in document.attribute_mappings:
                            if len(document.attribute_mappings[attribute.name]) > 0:
                                best_guesses.append((document.name, document.attribute_mappings[attribute.name][0].serializable))
                            else:
                                best_guesses.append((document.name, None))
                        else:
                            current_guess: InformationNugget = document.nuggets[document[CurrentMatchIndexSignal]]
                            if current_guess[CachedDistanceSignal] < self._max_distance:
                                best_guesses.append((document.name, current_guess.serializable))
                            else:
                                best_guesses.append((document.name, None))
                    statistics[attribute.name]["best_guesses"].append((num_feedback, best_guesses))

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

            statistics[attribute.name]["runtime"] = tak - start_matching

    def _update_new_nugget_contexts(self, new_docs: List[Document], added_reason: AddedReason,
                                    old_distances: Dict[InformationNugget, float]):
        best_matches: List[InformationNugget] = [new_doc.nuggets[new_doc[CurrentMatchIndexSignal]] for new_doc in
                                                 new_docs]

        self._new_nugget_contexts.extend([NewlyAddedNuggetContext(nugget,
                                                                  old_distances[nugget] if nugget in old_distances else None,
                                                                  nugget[CachedDistanceSignal],
                                                                  added_reason)
                                          for nugget in best_matches if nugget not in self._old_feedback_nuggets])

    def _compute_threshold_position_updates(self, document_base, old_distances):
        threshold_position_updates: Dict[str, Tuple[ThresholdPositionUpdate, Optional[ThresholdPositionUpdate]]] = dict()

        for nugget in document_base.nuggets:
            is_best_guess = nugget.document.nuggets[nugget.document[CurrentMatchIndexSignal]].text == nugget.text
            if not is_best_guess:
                continue

            old_update = threshold_position_updates[nugget.text][0] if nugget.text in threshold_position_updates else None

            if self._old_max_distance == -1:
                old_threshold_position = None
            else:
                old_threshold_position = ThresholdPosition.ABOVE if old_distances[nugget] > self._old_max_distance \
                    else ThresholdPosition.BELOW
            new_threshold_position = ThresholdPosition.ABOVE if nugget[CachedDistanceSignal] > self._max_distance \
                else ThresholdPosition.BELOW
            if old_threshold_position != new_threshold_position:
                if (old_update is not None and
                        old_update.old_position == old_threshold_position and
                        old_update.new_position == new_threshold_position):
                    threshold_position_updates[nugget.text] = (ThresholdPositionUpdate(nugget.text,
                                                                                       old_threshold_position,
                                                                                       new_threshold_position,
                                                                                       old_distances[nugget] if nugget in old_distances else None,
                                                                                       nugget[CachedDistanceSignal],
                                                                                       old_update.count + 1),
                                                               None)
                elif old_update is not None:
                    threshold_position_updates[nugget.text] = (old_update,
                                                               ThresholdPositionUpdate(nugget.text,
                                                                                       old_threshold_position,
                                                                                       new_threshold_position,
                                                                                       old_distances[nugget] if nugget in old_distances else None,
                                                                                       nugget[CachedDistanceSignal],
                                                                                       1))
                else:
                    threshold_position_updates[nugget.text] = (ThresholdPositionUpdate(nugget.text,
                                                                                       old_threshold_position,
                                                                                       new_threshold_position,
                                                                                       old_distances[nugget] if nugget in old_distances else None,
                                                                                       nugget[CachedDistanceSignal],
                                                                                       1),
                                                               None)

        result = []
        for first_update, second_update in threshold_position_updates.values():
            if second_update is None:
                result.append(first_update)
            else:
                result.extend([first_update, second_update])

        return result

    def to_config(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier,
            "distance": self._distance.to_config(),
            "max_num_feedback": self._max_num_feedback,
            "len_ranked_list": self._len_ranked_list,
            "max_distance": self._max_distance,
            "num_random_docs": self._num_random_docs,
            "num_bad_docs": self.num_bad_docs,
            "num_recent_docs": self.num_recent_docs,
            "sampling_mode": self._sampling_mode,
            "adjust_threshold": self._adjust_threshold,
            "extractor": self._find_additional_nuggets.to_config(),
            "nugget_pipeline": self._nugget_pipeline.to_config()
        }

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "RankingBasedMatcher":
        distance: BaseDistance = BaseDistance.from_config(config["distance"])
        return cls(distance, config["max_num_feedback"], config["len_ranked_list"], config["max_distance"],
                   config["num_random_docs"], config["sampling_mode"], config["adjust_threshold"],
                   Pipeline.from_config(config["nugget_pipeline"]))

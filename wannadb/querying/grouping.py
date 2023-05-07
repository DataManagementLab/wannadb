import abc
import itertools
import logging
from typing import Dict, Any, List, Tuple, Set

import numpy as np

from wannadb.configuration import BasePipelineElement, register_configurable_element
from wannadb.data.data import DocumentBase, Attribute, InformationNugget
from wannadb.interaction import BaseInteractionCallback
from wannadb.matching.distance import BaseDistance
from wannadb.statistics import Statistics
from wannadb.status import BaseStatusCallback

logger: logging.Logger = logging.getLogger(__name__)


class BaseGrouper(BasePipelineElement, abc.ABC):
    """
    Base class for all groupers.

    A grouper can group rows based on their matches for an attribute.
    """
    identifier: str = "BaseGrouper"


@register_configurable_element
class MergeGrouper(BaseGrouper):
    """Grouper that works by interactively merging groups based on the distances between the nuggets."""
    identifier: str = "MergeGrouper"

    required_signal_identifiers: Dict[str, List[str]] = {  # TODO
        "nuggets": [],
        "attributes": [],
        "documents": []
    }

    generated_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [],
        "attributes": [],
        "documents": []
    }

    def __init__(
            self,
            distance: BaseDistance,
            max_tries_no_merge: int,
            skip: int,
            automatically_merge_same_surface_form: bool
    ) -> None:
        """
        Initialize the MergeGrouper.

        :param distance: distance function
        :param max_tries_no_merge: number of tries that are confirmed to not be merges before stopping
        :param skip: number of pairs to skip feedback on
        :param automatically_merge_same_surface_form: whether to automatically merge nuggets with the same surface form
        """
        super(MergeGrouper, self).__init__()
        self._distance: BaseDistance = distance
        self._max_tries_no_merge: int = max_tries_no_merge
        self._skip: int = skip
        self._automatically_merge_same_surface_form: bool = automatically_merge_same_surface_form

        # add signals required by the distance function to the signals required by the matcher
        self._add_required_signal_identifiers(self._distance.required_signal_identifiers)

        logger.debug(f"Initialized {self.identifier}.")

    def _call(
            self,
            document_base: DocumentBase,
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:

        # decide on attribute to group
        feedback_result: Dict[str, Any] = interaction_callback(
            self.identifier,
            {
                "request-name": "get-attribute",
                "attributes": document_base.attributes
            }
        )

        attribute: Attribute = feedback_result["attribute"]
        statistics["attribute_name"] = attribute.name

        # start clustering: every nugget is in its own cluster
        nuggets: List[InformationNugget] = []
        for matching_nuggets in document_base.get_column_for_attribute(attribute):
            if matching_nuggets is None:
                logger.error(f"Document does not know of attribute '{attribute.name}'!")
                assert False, f"Document does not know of attribute '{attribute.name}'!"
            else:
                if matching_nuggets != []:
                    nuggets.append(matching_nuggets[0])  # only consider the first match

        clusters: Dict[int, List[InformationNugget]] = {
            idx: [nugget] for idx, nugget in enumerate(nuggets)
        }
        confirmed_as_distinct: Set[Tuple[int, int]] = set()

        inter_cluster_distances: np.ndarray = self._distance.compute_distances(nuggets, nuggets, statistics["distance"])

        def merge_clusters(
                index_a: int,
                index_b: int,
                clusters: Dict[int, List[InformationNugget]],
                inter_cluster_distances: np.ndarray,
                confirmed_as_distinct: Set[Tuple[int, int]]
        ):
            """Merges the two clusters into the cluster with index_a."""
            clusters[index_a] += clusters[index_b]
            del clusters[index_b]

            # replace index_b with index_a in confirmed_as_distinct
            new_confirmed_as_distinct: Set[Tuple[int, int]] = set()
            for ix_a, ix_b in confirmed_as_distinct:
                if ix_a == index_b:
                    new_confirmed_as_distinct.add((index_a, ix_b))
                if ix_b == index_b:
                    new_confirmed_as_distinct.add((ix_a, index_a))
                else:
                    new_confirmed_as_distinct.add((ix_a, ix_b))
            confirmed_as_distinct = new_confirmed_as_distinct

            # choose lower distances as distances for index_a
            for ix_b in clusters.keys():
                min_val = min(inter_cluster_distances[index_a, ix_b], inter_cluster_distances[index_b, ix_b])
                inter_cluster_distances[index_a, ix_b] = min_val
                inter_cluster_distances[ix_b, index_a] = min_val

            return clusters, inter_cluster_distances, confirmed_as_distinct

        # merge by surface form
        if self._automatically_merge_same_surface_form:
            for ix_a, ix_b in itertools.product(clusters.keys(), clusters.keys()):
                if ix_a != ix_b and ix_a in clusters.keys() and ix_b in clusters.keys():
                    if clusters[ix_a][0].text == clusters[ix_b][0].text:
                        clusters, inter_cluster_distances, confirmed_as_distinct = merge_clusters(
                            ix_a, ix_b, clusters, inter_cluster_distances, confirmed_as_distinct
                        )
                        statistics["num_merges_same_surface_form"] += 1

        # merge interactively
        num_not_same_cluster: int = 0
        current_skip: int = self._skip
        while len(clusters.keys()) > 1 and num_not_same_cluster < self._max_tries_no_merge:

            # determine the pair to present to the user for feedback
            pairs_and_distances: List[Tuple[Tuple[int, int], float]] = []
            for ix_a, ix_b in itertools.product(clusters.keys(), clusters.keys()):
                if ix_a < ix_b and (ix_a, ix_b) not in confirmed_as_distinct and \
                        (ix_b, ix_a) not in confirmed_as_distinct:
                    pairs_and_distances.append(((ix_a, ix_b), inter_cluster_distances[ix_a, ix_b]))

            if pairs_and_distances == []:
                logger.info("No more clusters can be merged!")
                break

            pairs_and_distances = list(sorted(pairs_and_distances, key=lambda x: x[1]))
            right: int = min(current_skip + 1, len(pairs_and_distances))
            pairs: List[Tuple[int, int]] = [pair_and_distance[0] for pair_and_distance in pairs_and_distances[:right]]
            idx_a, idx_b = pairs[-1]

            # ask the user for feedback
            statistics["num_feedback"] += 1
            statistics[f"num_feedback_at_skip_{current_skip}"] += 1
            feedback_result: Dict[str, Any] = interaction_callback(
                self.identifier,
                {
                    "request-name": "same-cluster-feedback",
                    "cluster-1": clusters[idx_a],
                    "cluster-2": clusters[idx_b],
                    "inter-cluster-distance": inter_cluster_distances[idx_a, idx_b],
                    "clusters": list(clusters.values())
                }
            )

            num_merged: int = 0
            if feedback_result["feedback"]:  # feedback ==> the two clusters are the same
                statistics["num_feedback_same_cluster"] += 1
                statistics[f"num_feedback_same_cluster_at_skip_{current_skip}"] += 1
                statistics["num_confirmed_merges"] += 1
                num_not_same_cluster = 0
                current_skip = self._skip

                confirmed = True
                while pairs != []:
                    idx_a, idx_b = pairs[-1]

                    if (idx_a, idx_b) not in confirmed_as_distinct and (idx_b, idx_a) not in confirmed_as_distinct:
                        # first merge is confirmed, rest is guessed
                        if not confirmed:
                            statistics["num_guessed_merges"] += 1
                        confirmed = False

                        # merge the two clusters into idx_a
                        num_merged += 1
                        clusters, inter_cluster_distances, confirmed_as_distinct = merge_clusters(
                            idx_a, idx_b, clusters, inter_cluster_distances, confirmed_as_distinct
                        )

                        # replace idx_b with idx_a in pairs and remove current pair
                        new_pairs: List[Tuple[int, int]] = []
                        for ix_a, ix_b in pairs[:-1]:
                            if ix_a == idx_b:
                                if ix_b != idx_a:
                                    new_pairs.append((idx_a, ix_b))
                            elif ix_b == idx_b:
                                if ix_a != idx_a:
                                    new_pairs.append((ix_a, idx_a))
                            else:
                                new_pairs.append((ix_a, ix_b))
                        pairs = new_pairs
                    else:  # guessed match blocked by confirmed_not_same_indexes
                        statistics["num_blocked_guessed_merges"] += 1

            else:
                statistics["num_feedback_not_same_cluster"] += 1
                statistics[f"num_feedback_not_same_cluster_at_skip_{current_skip}"] += 1
                num_not_same_cluster += 1
                current_skip = current_skip // 2
                confirmed_as_distinct.add((idx_a, idx_b))

            logger.info(f"Number of clusters merged in this step: {num_merged}")
            logger.info(f"Number of remaining clusters: {len(clusters.keys())}")

        feedback_result: Dict[str, Any] = interaction_callback(
            self.identifier,
            {
                "request-name": "output-clusters",
                "clusters": clusters
            }
        )

    def to_config(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier,
            "distance": self._distance.to_config(),
            "max_tries_no_merge": self._max_tries_no_merge,
            "skip": self._skip,
            "automatically_merge_same_surface_form": self._automatically_merge_same_surface_form
        }

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "MergeGrouper":
        distance: BaseDistance = BaseDistance.from_config(config["distance"])
        return cls(distance, config["max_tries_no_merge"], config["skip"],
                   config["automatically_merge_same_surface_form"])

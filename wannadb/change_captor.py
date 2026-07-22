"""
Class providing model classes which can be utilized to capture the changes due a user feedback and propagate them to the
UI.
These changes are computed after every feedback of the user.
"""

from typing import Optional, Union, List

from PyQt6.QtGui import QColor

from wannadb.data.data import InformationNugget
from wannadb_ui.common import ThresholdPosition, AddedReason


class BestMatchUpdate:
    """
    Instances of this class represent an update of the best match of a document.

    Each instance provide the old best match and the new best match of a document as well as the count specifying how
    often similar changes of best guesses happened.
    Another best match change is considered as similar if it happened in the same feedback round and the new best guess
    is equal.

    Methods
    -------
    old_best_match()
        Returns the old best match of the related document.
    new_best_match()
        Returns the new best match of the related document.
    count()
        Returns the count of similar best match changes happened in the same feedback round.
    """

    def __init__(self, old_best_match: str, new_best_match: str, count: int):
        """
        Parameters
        ----------
        old_best_match: str
            The old best match of the related document.
        new_best_match: str
            The new best match of the related document.
        count: int
            The count of similar best match changes happened in the same feedback round.
        """

        self._old_best_match: str = old_best_match
        self._new_best_match: str = new_best_match
        self._count: int = count

    @property
    def old_best_match(self) -> str:
        return self._old_best_match

    @property
    def new_best_match(self) -> str:
        return self._new_best_match

    @property
    def count(self) -> int:
        return self._count


class ThresholdPositionUpdate:
    """
    Instances of this class represent an update of the position of a nugget's distance relative to the threshold.

    Each instance provide the text of the nugget whose position changed, the old position (above or below), the new
    position (above or below), the old and new distance of the nugget as well as a count indicating how often similar
    changes happened in the same feedback round.
    A change is considered as similar if it happened in the same feedback round, the text represented by the nugget is
    equal, and it has the same type of the update (above -> below or below -> above).

    As mentioned, an instance of this class can cover multiple changes if the text of the nuggets with a change are
    equal.
    In this case the distance related properties are None as we don't refer to a single nugget.
    """

    def __init__(self,
                 nugget_text: str,
                 old_position: Optional[ThresholdPosition], new_position: ThresholdPosition,
                 old_distance: Optional[float], new_distance: Optional[float],
                 count: int):
        """
        Parameters
        ----------
        nugget_text: str
            Text of the nuggets whose position relative to the threshold changed.
        old_position: ThresholdPosition
            Previous position of the covered nuggets relative to the threshold (above or below).
        new_position: ThresholdPosition
            New position of the covered nuggets relative to the threshold (above or below).
        old_distance: float
            Old distance associated with the nugget. If multiple nuggets are covered by this instance, this will be
            None.
        new_distance: float
            New distance associated with the nugget. If multiple nuggets are covered by this instance, this will be
            None.
        count: int
            Number of similar changes happened in the same feedback round.
        """

        self._best_guess: str = nugget_text
        self._old_position: Optional[ThresholdPosition] = old_position
        self._new_position: ThresholdPosition = new_position
        self._old_distance: float = old_distance
        self._new_distance: float = new_distance
        self._count: int = count

    @property
    def nugget_text(self) -> str:
        return self._best_guess

    @property
    def old_position(self) -> Optional[ThresholdPosition]:
        return self._old_position

    @property
    def new_position(self) -> ThresholdPosition:
        return self._new_position

    @property
    def old_distance(self) -> Optional[float]:
        return self._old_distance

    @property
    def new_distance(self) -> Optional[float]:
        return self._new_distance

    @property
    def count(self) -> int:
        return self._count


class NewlyAddedNuggetContext:
    """
    Instances of this class represent a newly added nugget to the document overview.
    Each instance provide information about the old and new distance of the nugget as well as the reason why the system
    newly added the nugget.
    """

    def __init__(self,
                 nugget: InformationNugget,
                 old_distance: Union[float, None],
                 new_distance: float,
                 added_reason: AddedReason):
        """
        Parameters
        ----------
        nugget: InformationNugget
            Newly added nugget.
        old_distance: float
            Old distance associated with the nugget.
        new_distance: float
            New distance associated with the nugget.
        added_reason: AddedReason
            Reason for the nugget being newly added.
        """

        self._nugget = nugget
        self._old_distance = old_distance
        self._new_distance = new_distance
        self._added_reason = added_reason

    @property
    def nugget(self):
        return self._nugget

    @property
    def old_distance(self):
        return self._old_distance

    @property
    def new_distance(self):
        return self._new_distance

    @property
    def added_reason(self):
        return self._added_reason


class NuggetUpdatesContext:
    """
    Wrapper class wrapping multiple types of nugget related updates.
    Nugget related updates refer to `NewlyAddedNuggetContext`, `ThresholdPositionUpdate` and `BestMatchUpdate`. Each
    instance holds a list of updates for all of these 3 update types.
    """

    def __init__(self,
                 newly_added_nugget_contexts: List[NewlyAddedNuggetContext],
                 best_match_updates: List[BestMatchUpdate],
                 threshold_position_updates: List[ThresholdPositionUpdate]):
        """
        Parameters
        ----------
        newly_added_nugget_contexts: List[NewlyAddedNuggetContext]
            List of all `NewlyAddedNuggetContext` instances wrapped by this instance.
        best_match_updates: List[BestMatchUpdate]
            List of all `BestMatchUpdate` instances wrapped by this instance.
        threshold_position_updates: List[ThresholdPositionUpdate]
            List of all `ThresholdPositionUpdate` instances wrapped by this instance.
        """

        self._newly_added_nugget_contexts: List[NewlyAddedNuggetContext] = newly_added_nugget_contexts
        self._best_match_updates: List[BestMatchUpdate] = best_match_updates
        self._threshold_position_updates: List[ThresholdPositionUpdate] = threshold_position_updates

    @property
    def newly_added_nugget_contexts(self) -> List[NewlyAddedNuggetContext]:
        return self._newly_added_nugget_contexts

    @property
    def best_match_updates(self) -> List[BestMatchUpdate]:
        return self._best_match_updates

    @property
    def threshold_position_updates(self) -> List[ThresholdPositionUpdate]:
        return self._threshold_position_updates




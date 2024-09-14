from typing import Optional, Union, List

from PyQt6.QtGui import QColor

from wannadb.data.data import InformationNugget
from wannadb_ui.common import ThresholdPosition, AddedReason


class BestMatchUpdate:
    def __init__(self, old_best_match: str, new_best_match: str, count: int):
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
    def __init__(self, best_guess: str,
                 old_position: Optional[ThresholdPosition], new_position: ThresholdPosition,
                 old_distance: Optional[float], new_distance: float,
                 count: int):
        self._best_guess: str = best_guess
        self._old_position: Optional[ThresholdPosition] = old_position
        self._new_position: ThresholdPosition = new_position
        self._old_distance: float = old_distance
        self._new_distance: float = new_distance
        self._count: int = count

    @property
    def best_guess(self) -> str:
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
    def new_distance(self) -> float:
        return self._new_distance

    @property
    def count(self) -> int:
        return self._count


class NewlyAddedNuggetContext:
    def __init__(self, nugget: InformationNugget,
                 old_distance: Union[float, None],
                 new_distance: float,
                 added_reason: AddedReason):
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
    def __init__(self,
                 newly_added_nugget_contexts: List[NewlyAddedNuggetContext],
                 best_match_updates: List[BestMatchUpdate],
                 threshold_position_updates: List[ThresholdPositionUpdate]):
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


class AccessibleColor:
    def __init__(self, color: QColor, corresponding_accessible_color: QColor):
        self._color = color
        self._corresponding_accessible_color = corresponding_accessible_color

    @property
    def color(self):
        return self._color

    @property
    def corresponding_accessible_color(self):
        return self._corresponding_accessible_color
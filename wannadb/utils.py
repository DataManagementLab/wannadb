"""
Utility class providing common functionality.
"""

import math

import numpy as np
from PyQt6.QtGui import QColor


def get_possible_duplicate(nugget_to_check, nugget_list):
    """
    Checks the given list for duplicates of the given nugget and returns the first occurring duplicate if present and
    its index in the list.

    The check whether a nugget duplicates another is realized by the `duplicates(other) -> bool` function of the
    `InformationNugget` class.
    """

    for idx, nugget in enumerate(nugget_list):
        if nugget_to_check.duplicates(nugget):
            return nugget, idx

    return None, None


def positions_equal(position1: np.ndarray, position2: np.ndarray) -> bool:
    """
    Checks if the given arrays are equal meaning that each element of the first array is close enough to the
    corresponding value in the second array.
    The check for closeness is realized by `math.isclose(...)` function.

    Handles only (1, 3) shaped arrays as this function should only be used for arrays representing 3-dimensional
    positions.
    If one of the given arrays doesn't conform to this shape, the function returns `False`.

    Returns
    -------
    Whether the given arrays are considered as equal according to the explanation above.
    """

    if position1.shape != (1, 3) or position2.shape != (1, 3):
        return False

    return (math.isclose(position1[0][0], position2[0][0], rel_tol=1e-05, abs_tol=1e-05) and
            math.isclose(position1[0][1], position2[0][1], rel_tol=1e-05, abs_tol=1e-05) and
            math.isclose(position1[0][2], position2[0][2], rel_tol=1e-05, abs_tol=1e-05))


def embeddings_equal(embedding1: np.ndarray, embedding2: np.ndarray) -> bool:
    if embedding1.shape != embedding2.shape:
        return False

    arrays_are_close = np.vectorize(math.isclose)
    return arrays_are_close(embedding1, embedding2, rel_tol=1e-05, abs_tol=1e-05).all()


class AccessibleColor:
    """
    Utility model class wrapping a color and its corresponding accessible color that is better understandable by users
    suffering from color blindness.
    """

    def __init__(self, color: QColor, corresponding_accessible_color: QColor):
        """
        Parameters
        ----------
        color: QColor
            Color represented by this instance.
        corresponding_accessible_color: QColor
            Accessible color corresponding to the given standard version of the color.
        """

        self._color = color
        self._corresponding_accessible_color = corresponding_accessible_color

    @property
    def color(self):
        return self._color

    @property
    def corresponding_accessible_color(self):
        return self._corresponding_accessible_color

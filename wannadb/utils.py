import math

import numpy as np


def get_possible_duplicate(nugget_to_check, nugget_list):
    for idx, nugget in enumerate(nugget_list):
        if nugget_to_check.duplicates(nugget):
            return nugget, idx

    return None, None


def positions_equal(pos1: np.ndarray, pos2: np.ndarray) -> bool:
    if pos1.shape != (1, 3) or pos2.shape != (1, 3):
        return False
    return (math.isclose(pos1[0][0], pos2[0][0], rel_tol=1e-05, abs_tol=1e-05) and
            math.isclose(pos1[0][1], pos2[0][1], rel_tol=1e-05, abs_tol=1e-05) and
            math.isclose(pos1[0][2], pos2[0][2], rel_tol=1e-05, abs_tol=1e-05))


def embeddings_equal(embedding1: np.ndarray, embedding2: np.ndarray) -> bool:
    if embedding1.shape != embedding2.shape:
        return False

    arrays_are_close = np.vectorize(math.isclose)
    return arrays_are_close(embedding1, embedding2, rel_tol=1e-05, abs_tol=1e-05).all()

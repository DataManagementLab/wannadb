def consider_overlap_as_match(true_start, true_end, pred_start, pred_end):
    """Determines whether the predicted span is considered a match of the true span."""
    # considered as overlap if at least half of the larger span
    pred_length = pred_end - pred_start
    true_length = true_end - true_start

    valid_overlap = max(pred_length // 2, true_length // 2, 1)

    if pred_start <= true_start:
        actual_overlap = min(pred_end - true_start, true_length)
    else:
        actual_overlap = min(true_end - pred_start, pred_length)

    return actual_overlap >= valid_overlap


def calculate_f1_scores(results):
    # compute the evaluation metrics per attribute

    # recall
    if (results["num_should_be_filled_is_correct"] + results["num_should_be_filled_is_incorrect"] + results["num_should_be_filled_is_empty"]) == 0:
        results["recall"] = 1
    else:
        results["recall"] = results["num_should_be_filled_is_correct"] / (
                results["num_should_be_filled_is_correct"] + results["num_should_be_filled_is_incorrect"] +
                results["num_should_be_filled_is_empty"])

    # precision
    if (results["num_should_be_filled_is_correct"] + results["num_should_be_filled_is_incorrect"] + results["num_should_be_empty_is_full"]) == 0:
        results["precision"] = 1
    else:
        results["precision"] = results["num_should_be_filled_is_correct"] / (
                results["num_should_be_filled_is_correct"] + results["num_should_be_filled_is_incorrect"] + results["num_should_be_empty_is_full"])

    # f1 score
    if results["precision"] + results["recall"] == 0:
        results["f1_score"] = 0
    else:
        results["f1_score"] = (
                2 * results["precision"] * results["recall"] / (results["precision"] + results["recall"]))

    # true negative rate
    if results["num_should_be_empty_is_empty"] + results["num_should_be_empty_is_full"] == 0:
        results["true_negative_rate"] = 1
    else:
        results["true_negative_rate"] = results["num_should_be_empty_is_empty"] / (results["num_should_be_empty_is_empty"] + results["num_should_be_empty_is_full"])

    # true positive rate
    if results["num_should_be_filled_is_correct"] + results["num_should_be_filled_is_incorrect"] + results["num_should_be_filled_is_empty"] == 0:
        results["true_positive_rate"] = 1
    else:
        results["true_positive_rate"] = results["num_should_be_filled_is_correct"] / (results["num_should_be_filled_is_correct"] + results["num_should_be_filled_is_incorrect"] + results["num_should_be_filled_is_empty"])

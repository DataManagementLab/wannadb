import os
import matplotlib.pyplot as plt
import json
import pickle
import pandas as pd
import numpy as np


# Dataset to be evaluated
DATASET = "nobel"

# Path toward the folder of results
PATH = os.path.join("results", DATASET, "feedback")

# Path toward folder of plots
PLOT_PATH = os.path.join("results", "plots")

# Order of the extractor identifier by which the plots are to be sorted
ORDER = [
    "ExactCustomMatchExtractor",
    "FaissSemanticSimilarityExtractor",
    "QuestionAnsweringCustomMatchExtractor",
    "WordNetSimilarityCustomMatchExtractor",
    "CustomHighlightExtractor"
]

# Pretty labels for the plots in correspondence to above extractors
PRETTY_LABELS = [
    "ExactMatcher [Baseline]",
    "FaissIndexingMatcher",
    "QuestionAnsweringMatcher",
    "WordNetMatcher",
    "SpacyMatcher"
]

# Dict of colors that are used
COLORS = {
    "RED": "#b90f22",
    "BLUE": "#29339b",
    "VIOLET": "#69306d",
    "GREEN": "#007540",
    "ORANGE": "#ffbc42"
}


def load_experiment_results():

    df = None
    attributes_names = []
    attribute_col_names = []

    for extractor_str in os.listdir(PATH):

        # If the extractor string is not in the list of the order above: Do not fetch its results
        if extractor_str not in ORDER:
            continue

        for interactions in [10, 20, 30]:

            # Join path to the extractor file
            path_extractor = os.path.join(PATH, extractor_str, str(interactions))

            # Load in the results json
            with open(os.path.join(path_extractor, "exp-3.json"), "r") as f:
                results = json.load(f)

            # Load in the timekeeping df
            with open(os.path.join(path_extractor, "time_keeping.pkl"), "rb") as f:
                time_df = pickle.load(f)

            # List of attributes
            attributes = results["dataset"]["attributes"]

            # Create df if it does not yet exist
            if df is None:
                cols = ["extractor", "interactions", "mean_inference_time", "final_f1"]
                attribute_col_names = [atr + "_f1" for atr in attributes]
                attributes_names = attributes
                cols.extend(attribute_col_names)
                df = pd.DataFrame(columns=cols)

            # Extract necessary data
            final_f1_score = results["matching"]["results"]["final_macro_f1"]
            attributes_f1_scores = []
            for atr in attributes:
                attributes_f1_scores.append(results["matching"]["results"][atr]["f1_score"])

            # Fill the df with the proper row
            new_row = [
                extractor_str,
                interactions,
                (time_df["time"] / time_df["remaining_documents"]).mean(),
                final_f1_score
            ]
            new_row.extend(attributes_f1_scores)
            df.loc[df.shape[0]] = new_row

    return df.sort_values(
        by="extractor", ascending=True, key=lambda x: x.apply(lambda y: ORDER.index(y))
    ), attribute_col_names, attributes_names


def main():

    # Create directory for where to save the plots to
    if not os.path.exists(PLOT_PATH):
        os.mkdir(PLOT_PATH)

    # Some settings for pretty plots
    plt.rcParams["font.family"] = "Times New Roman"
    plt.rcParams["font.size"] = 18

    # Get the df of experiment results and the proper names in the df
    df, attribute_col_names, attributes_names = load_experiment_results()

    # --- PLOT F1 SCORES PER EXTRACTOR PER ATTRIBUTE --- #

    # Get proper slices of the df
    interactions = 30
    this_interaction_slice = df[df["interactions"] == interactions]

    # Create the figure
    fig, ax = plt.subplots(figsize=(len(attribute_col_names) * 4, 7))

    # Grid layout, labels, legends etc
    ax.grid(True, linestyle='--', linewidth=0.9, alpha=0.75, zorder=-1)
    ax.set_ylim((0, 1.03))
    ax.set_ylabel("Mean F1 score")
    tick_lst = [8 * x for x in range(len(attribute_col_names))]
    tick_label_lst = attributes_names
    ax.set_xticks(tick_lst, labels=tick_label_lst, rotation=0, ha="center")

    # List of colors in desired order
    cols = [COLORS["ORANGE"], COLORS["BLUE"], COLORS["RED"], COLORS["VIOLET"], COLORS["GREEN"]]

    # Create a bar for each model and use offset to align bars properly
    for model, offset, pretty_label, col in zip(
            df["extractor"].value_counts().index,
            [2, 1, 0, -1, -2],
            PRETTY_LABELS,
            cols
    ):
        # Create a bar for this model with its offset and color
        plt.bar(
            np.array(list(range(len(attribute_col_names)))) * 8 + offset,
            this_interaction_slice[this_interaction_slice["extractor"] == model][attribute_col_names].values[0],
            zorder=2,
            edgecolor="black",
            label=pretty_label,
            color=col
        )

    # Show plot and save
    plt.legend()
    plt.title(f"{DATASET} evaluation with #interactions = {interactions}")
    plt.savefig(os.path.join(PLOT_PATH, f"mean_f1_{DATASET}_{interactions}.pdf"), bbox_inches='tight')

    # --- PLOT INFERENCE TIMES PER EXTRACTOR --- #

    # Basic setup
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.grid(True, linestyle='--', linewidth=0.9, alpha=0.75, zorder=-2)
    ax.set_ylabel("Time [s]")

    # Get values
    extractors = df["extractor"].value_counts().index.tolist()
    times = [df[df["extractor"] == ex]["mean_inference_time"].mean() for ex in extractors]

    # Create bars per extractor
    for idx, (ex, time, color, lab) in enumerate(zip(extractors, times, cols, PRETTY_LABELS)):
        ax.bar([idx], time, color=color, zorder=2, label=lab)

    # Save plot
    ax.set_xticks(range(len(extractors)), labels=PRETTY_LABELS, rotation=50, ha="right")
    plt.title(f"Mean inference time per document in {DATASET}")
    plt.savefig(os.path.join(PLOT_PATH, f"time_{DATASET}.pdf"), bbox_inches='tight')


if __name__ == '__main__':
    main()

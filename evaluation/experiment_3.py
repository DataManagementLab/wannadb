from wannadb.resources import ResourceManager
from wannadb.statistics import Statistics
from evaluation.datasets.aviation import aviation
from evaluation.datasets.nobel import nobel
from evaluation.automatic_feedback import AutomaticRandomRankingBasedMatchingFeedback,\
    AutomaticRandomCustomMatchingFeedback
from evaluation.util import consider_overlap_as_match, calculate_f1_scores
from wannadb.data.data import Attribute, Document, DocumentBase
from wannadb.preprocessing.embedding import BERTContextSentenceEmbedder, RelativePositionEmbedder, SBERTTextEmbedder,\
    SBERTLabelEmbedder
from wannadb.preprocessing.extraction import StanzaNERExtractor, SpacyNERExtractor
from wannadb.preprocessing.label_paraphrasing import OntoNotesLabelParaphraser, SplitAttributeNameLabelParaphraser
from wannadb.preprocessing.normalization import CopyNormalizer
from wannadb.preprocessing.other_processing import ContextSentenceCacher
from wannadb.interaction import EmptyInteractionCallback
from wannadb.status import EmptyStatusCallback
from wannadb.configuration import Pipeline
from wannadb.matching.distance import SignalsMeanDistance
from wannadb.matching.matching import RankingBasedMatcher
from wannadb.matching.custom_match_extraction import QuestionAnsweringCustomMatchExtractor,\
    FaissSemanticSimilarityExtractor
import os
import random
import numpy as np
import json
import matplotlib.pyplot as plt
import seaborn as sns


DATASETS = [("aviation", aviation), ("nobel", nobel)]

RESULTS_FILENAME = r"exp-3.json"


def load_dataset(statistics, dataset):
    documents = dataset.load_dataset()

    statistics["dataset"]["dataset_name"] = dataset.NAME
    statistics["dataset"]["attributes"] = dataset.ATTRIBUTES
    statistics["dataset"]["num_documents"] = len(documents)

    for attribute in dataset.ATTRIBUTES:
        statistics["dataset"]["num_mentioned"][attribute] = 0
        for document in documents:
            if document["mentions"][attribute]:
                statistics["dataset"]["num_mentioned"][attribute] += 1

    return documents


def create_document_base(statistics, dataset, documents):
    user_attribute_names = dataset.ATTRIBUTES
    statistics["user_provided_attribute_names"] = user_attribute_names
    user_attribute_name2attribute_name = {
        u_attr_name: attr_name for u_attr_name, attr_name in zip(user_attribute_names, dataset.ATTRIBUTES)
    }

    document_base = DocumentBase(
        documents=[Document(doc["id"], doc["text"]) for doc in documents],
        attributes=[Attribute(attribute_name) for attribute_name in user_attribute_names]
    )

    return user_attribute_name2attribute_name, document_base


def preprocessing(statistics, dataset, document_base, documents):
    # See whether the given dataset has already been preprocessed once
    path = os.path.join(os.path.dirname(__file__), "..", "cache", f"exp-{dataset.NAME}-preprocessed.bson")

    # If not: Do preprocessing
    if not os.path.isfile(path):

        pipeline = Pipeline([
            StanzaNERExtractor(),
            SpacyNERExtractor("SpacyEnCoreWebLg"),
            ContextSentenceCacher(),
            CopyNormalizer(),
            OntoNotesLabelParaphraser(),
            SplitAttributeNameLabelParaphraser(do_lowercase=True, splitters=[" ", "_"]),
            SBERTLabelEmbedder("SBERTBertLargeNliMeanTokensResource"),
            SBERTTextEmbedder("SBERTBertLargeNliMeanTokensResource"),
            BERTContextSentenceEmbedder("BertLargeCasedResource"),
            RelativePositionEmbedder()
        ])

        statistics["preprocessing"]["config"] = pipeline.to_config()

        pipeline(
            document_base=document_base,
            interaction_callback=EmptyInteractionCallback(),
            status_callback=EmptyStatusCallback(),
            statistics=statistics["preprocessing"]
        )

        with open(path, "wb") as file:
            file.write(document_base.to_bson())

    else:
        with open(path, "rb") as file:
            document_base = DocumentBase.from_bson(file.read())

    for attribute in dataset.ATTRIBUTES:
        statistics["preprocessing"]["results"]["num_extracted"][attribute] = 0
        for document, wannadb_document in zip(documents, document_base.documents):
            match = False
            for mention in document["mentions"][attribute]:
                for nugget in wannadb_document.nuggets:
                    if consider_overlap_as_match(mention["start_char"], mention["end_char"], nugget.start_char,
                                                 nugget.end_char):
                        match = True
                        break
            if match:
                statistics["preprocessing"]["results"]["num_extracted"][attribute] += 1

    return document_base


def main():

    with ResourceManager() as resource_manager:
        dataset_str = "nobel"

        # How many custom interactions are executed
        for number_of_interactions in [0]:

            # Create statistics object and get desired dataset
            statistics = Statistics(do_collect=True)
            dataset = DATASETS[[x[0] for x in DATASETS].index(dataset_str)][1]

            # Load dataset raw files
            documents = load_dataset(statistics, dataset)

            # Create document base from it and then apply preprocessing
            user_attribute_name2attribute_name, document_base = create_document_base(statistics, dataset, documents)
            user_attribute_names = statistics["user_provided_attribute_names"]
            preprocessing(statistics, dataset, document_base, documents)
            path = os.path.join(os.path.dirname(__file__), "..", "cache", f"exp-{dataset.NAME}-preprocessed.bson")

            # --- Matching phase --- #
            for attribute_name in dataset.ATTRIBUTES:
                statistics["matching"]["results"]["considered_as_match"][attribute_name] = set()

                # random seeds have been randomly chosen once from [0, 1000000]
                random_seeds = [200488, 422329, 449756] # [200488, 422329, 449756, 739608, 983889, 836016, 264198, 908457, 205619, 461905]

                for run, random_seed in enumerate(random_seeds):

                    print(f"Run {run}")

                    # Load the document base again
                    with open(path, "rb") as file:
                        document_base = DocumentBase.from_bson(file.read())

                    # Define the matching pipeline
                    matching_pipeline = Pipeline(
                        [
                            SplitAttributeNameLabelParaphraser(do_lowercase=True, splitters=[" ", "_"]),
                            ContextSentenceCacher(),
                            SBERTLabelEmbedder("SBERTBertLargeNliMeanTokensResource"),
                            RankingBasedMatcher(
                                distance=SignalsMeanDistance(
                                    signal_identifiers=[
                                        "LabelEmbeddingSignal",
                                        "TextEmbeddingSignal",
                                        "ContextSentenceEmbeddingSignal",
                                        "RelativePositionSignal"
                                    ]
                                ),
                                max_num_feedback=100,
                                len_ranked_list=10,
                                max_distance=0.2,
                                num_random_docs=1,
                                sampling_mode="AT_MAX_DISTANCE_THRESHOLD",
                                adjust_threshold=True,
                                nugget_pipeline=Pipeline(
                                    [
                                        ContextSentenceCacher(),
                                        CopyNormalizer(),
                                        OntoNotesLabelParaphraser(),
                                        SplitAttributeNameLabelParaphraser(do_lowercase=True, splitters=[" ", "_"]),
                                        SBERTLabelEmbedder("SBERTBertLargeNliMeanTokensResource"),
                                        SBERTTextEmbedder("SBERTBertLargeNliMeanTokensResource"),
                                        BERTContextSentenceEmbedder("BertLargeCasedResource"),
                                        RelativePositionEmbedder()
                                    ]
                                ),
                                find_additional_nuggets=QuestionAnsweringCustomMatchExtractor()
                            )
                        ]
                    )
                    statistics["matching"]["config"] = matching_pipeline.to_config()

                    # Set the random seed
                    random.seed(random_seed)

                    # Run the pipeline
                    matching_pipeline(
                        document_base=document_base,
                        interaction_callback=AutomaticRandomCustomMatchingFeedback(
                            documents,
                            user_attribute_name2attribute_name
                        ),
                        status_callback=EmptyStatusCallback(),
                        statistics=statistics["matching"]["runs"][str(run)]
                    )

                    # evaluate the matching process
                    for attribute, attribute_name in zip(dataset.ATTRIBUTES, user_attribute_names):
                        results = statistics["matching"]["runs"][str(run)]["results"][attribute]
                        results["num_should_be_filled_is_empty"] = 0
                        results["num_should_be_filled_is_correct"] = 0
                        results["num_should_be_filled_is_incorrect"] = 0
                        results["num_should_be_empty_is_empty"] = 0
                        results["num_should_be_empty_is_full"] = 0

                        for document, aset_document in zip(documents, document_base.documents):
                            found_nuggets = []
                            if attribute_name in aset_document.attribute_mappings.keys():
                                found_nuggets = aset_document.attribute_mappings[attribute_name]

                            if document["mentions"][attribute]:  # document states cell's value
                                if not found_nuggets:
                                    results["num_should_be_filled_is_empty"] += 1
                                else:
                                    found_nugget = found_nuggets[0]  # TODO: only considers the first found nugget
                                    for mention in document["mentions"][
                                        attribute]:  # + document["mentions_same_attribute_class"][attribute]
                                        if consider_overlap_as_match(mention["start_char"], mention["end_char"],
                                                                     found_nugget.start_char, found_nugget.end_char):
                                            results["num_should_be_filled_is_correct"] += 1
                                            break
                                    else:
                                        results["num_should_be_filled_is_incorrect"] += 1

                            else:  # document does not state cell's value
                                if found_nuggets == []:
                                    results["num_should_be_empty_is_empty"] += 1
                                else:
                                    results["num_should_be_empty_is_full"] += 1

                            # compute the evaluation metrics
                            calculate_f1_scores(results)

                    # compute Macro F1 over dataset:
                    attribute_f1_scores = []
                    for attribute in dataset.ATTRIBUTES:
                        calculate_f1_scores(statistics["matching"]["runs"][str(run)]["results"][attribute])
                        attribute_f1_scores.append(
                            statistics["matching"]["runs"][str(run)]["results"][attribute]["f1_score"])
                    results = statistics["matching"]["runs"][str(run)]["results"]["macro_f1"] = np.mean(
                        attribute_f1_scores)
                    print("F1 Score: ", np.mean(attribute_f1_scores))

                # compute the results over all runs
                for attribute in dataset.ATTRIBUTES:
                    for score in ["recall", "precision", "f1_score", "num_should_be_filled_is_empty",
                                  "num_should_be_filled_is_correct", "num_should_be_filled_is_incorrect",
                                  "num_should_be_empty_is_empty", "num_should_be_empty_is_full"]:
                        values = [res["results"][attribute][score] for res in
                                  statistics["matching"]["runs"].all_values()]
                        statistics["matching"]["results"][attribute][score] = np.median(values)
                statistics["matching"]["results"]["final_macro_f1"] = np.median(
                    [res["results"]["macro_f1"] for res in statistics["matching"]["runs"].all_values()])
                print("Overall Macro F1: ", statistics["matching"]["results"]["final_macro_f1"])

                ################################################################################################################
                # store the results
                ################################################################################################################
                path = os.path.join(os.path.dirname(__file__), "results", f"{dataset.NAME}", "feedback",
                                    f"{number_of_interactions}")
                if not os.path.isdir(path):
                    os.makedirs(path, exist_ok=True)
                path = str(os.path.join(path, RESULTS_FILENAME))
                with open(path, "w") as file:
                    json.dump(statistics.to_serializable(), file, indent=4)


                ################################################################################################################
                # draw plots
                ################################################################################################################
                attribute_names = statistics["dataset"]["attributes"]

                num_mentions = [statistics["dataset"]["num_mentioned"][attribute] for attribute in attribute_names]
                num_documents = statistics["dataset"]["num_documents"]
                percent_mentions = [y / num_documents * 100 for y in num_mentions]
                num_extracted = [statistics["preprocessing"]["results"]["num_extracted"][attribute] for attribute in
                                 attribute_names]
                percent_extracted = [y / x * 100 for x, y in zip(num_mentions, num_extracted)]
                recalls = [statistics["matching"]["results"][attribute]["recall"] for attribute in attribute_names]
                precisions = [statistics["matching"]["results"][attribute]["precision"] for attribute in
                              attribute_names]
                f1_scores = [statistics["matching"]["results"][attribute]["f1_score"] for attribute in attribute_names]

                ################################################################################################################
                # mentions by attribute
                ################################################################################################################
                _, ax = plt.subplots(figsize=(7, 5))
                sns.barplot(x=attribute_names, y=percent_mentions, ax=ax, color="#0c2461")
                ax.set_ylabel("% mentioned")
                ax.set_title("Percentage of Documents that Mention each Attribute", size=12)
                ax.tick_params(axis="x", labelsize=7)
                plt.xticks(rotation=20, ha='right')
                ax.set_ylim((0, 110))
                plt.subplots_adjust(0.09, 0.15, 0.99, 0.94)

                for x_value, percentage in zip(np.arange(len(attribute_names)), percent_mentions):
                    ax.text(
                        x_value,
                        percentage + 1,
                        str(int(round(percentage, 0))),
                        fontsize=9,
                        horizontalalignment="center"
                    )

                plt.savefig(path[:-5] + "-percent-mentioned.pdf", format="pdf", transparent=True)

                ################################################################################################################
                # percentage extracted by attribute
                ################################################################################################################
                _, ax = plt.subplots(figsize=(7, 5))
                sns.barplot(x=attribute_names, y=percent_extracted, ax=ax, color="#0c2461")
                ax.set_ylabel("% extracted")
                ax.set_title("Percentage of Extracted Mentions by Attribute", size=12)
                ax.tick_params(axis="x", labelsize=7)
                plt.xticks(rotation=20, ha='right')
                ax.set_ylim((0, 110))
                plt.subplots_adjust(0.09, 0.15, 0.99, 0.94)

                for x_value, percentage in zip(np.arange(len(attribute_names)), percent_extracted):
                    ax.text(
                        x_value,
                        percentage + 1,
                        str(int(round(percentage, 0))),
                        fontsize=9,
                        horizontalalignment="center"
                    )

                plt.savefig(path[:-5] + "-percent-extracted.pdf", format="pdf", transparent=True)

                ################################################################################################################
                # F1-Scores by attribute
                ################################################################################################################
                _, ax = plt.subplots(figsize=(7, 5))
                sns.barplot(x=attribute_names, y=f1_scores, ax=ax, color="#0c2461")
                ax.set_ylabel("F1 score")
                ax.set_title("E2E F1 Scores by Attribute", size=12)
                ax.tick_params(axis="x", labelsize=7)
                plt.xticks(rotation=20, ha='right')
                ax.set_ylim((0, 1.1))
                plt.subplots_adjust(0.09, 0.15, 0.99, 0.94)

                for x_value, percentage in zip(np.arange(len(attribute_names)), f1_scores):
                    ax.text(
                        x_value,
                        percentage + 0.01,
                        str(round(percentage, 2)),
                        fontsize=9,
                        horizontalalignment="center"
                    )

                plt.savefig(path[:-5] + "-f1-scores.pdf", format="pdf", transparent=True)


if __name__ == "__main__":
    main()
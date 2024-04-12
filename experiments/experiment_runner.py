import random
import time
import os
import json
import logging.config

from pathlib import Path
from typing import Dict, Any, List, Optional
from collections import Counter

from wannadb.data.data import Attribute
from wannadb.matching.custom_match_extraction import DummyCustomMatchExtractor
from wannadb.matching.distance import SignalsMeanDistance
from wannadb.matching.matching import RankingBasedMatcher
from wannadb.configuration import Pipeline
from wannadb.data.data import DocumentBase
from wannadb.preprocessing.embedding import BERTContextSentenceEmbedder, RelativePositionEmbedder, SBERTTextEmbedder, \
    SBERTLabelEmbedder, SBERTDocumentSentenceEmbedder
from wannadb.preprocessing.extraction import StanzaNERExtractor, SpacyNERExtractor
from wannadb.preprocessing.label_paraphrasing import OntoNotesLabelParaphraser, SplitAttributeNameLabelParaphraser
from wannadb.preprocessing.normalization import CopyNormalizer
from wannadb.preprocessing.other_processing import ContextSentenceCacher
from wannadb.resources import ResourceManager
from wannadb.statistics import Statistics
from wannadb.status import EmptyStatusCallback
from wannadb.interaction import BaseInteractionCallback

from experiments.util import consider_overlap_as_match, calculate_f1_scores
from experiments.automatic_feedback import AutomaticCustomMatchesRandomRankingBasedMatchingFeedback


class ExperimentRunner:
    def __init__(self, document_base: DocumentBase, ground_truth_docs: List[Dict[str, Any]],
                 user_attribute_name2attribute_name: Dict[str, str] = None, preprocessing_pipeline: Pipeline = None,
                 matching_pipeline: Pipeline = None, resource_manager: ResourceManager = None, statistics=None, logger=None, tmp_dir="."):
        self.document_base = document_base
        self.ground_truth_docs = ground_truth_docs

        self.tmp_dir = tmp_dir
        # Store document base in file to allow restoring a clean state for each run
        with(open(os.path.join(self.tmp_dir, "tmp_exp_document_base.bson"), "wb")) as file:
            file.write(document_base.to_bson())

        if user_attribute_name2attribute_name is None:
            # Generate default mapping (if not otherwise specified)
            user_attribute_name2attribute_name = {a: a for a in document_base.attributes}
        self.user_attribute_name2attribute_name = user_attribute_name2attribute_name

        if preprocessing_pipeline is None:
            # Default preprocessing pipeline
            preprocessing_pipeline = Pipeline([
                StanzaNERExtractor(),
                SpacyNERExtractor("SpacyEnCoreWebLg"),
                ContextSentenceCacher(),
                CopyNormalizer(),
                OntoNotesLabelParaphraser(),
                SplitAttributeNameLabelParaphraser(do_lowercase=True, splitters=[" ", "_"]),
                SBERTLabelEmbedder("SBERTBertLargeNliMeanTokensResource"),
                SBERTTextEmbedder("SBERTBertLargeNliMeanTokensResource"),
                BERTContextSentenceEmbedder("BertLargeCasedResource"),
                SBERTDocumentSentenceEmbedder("SBERTBertLargeNliMeanTokensResource"),
                RelativePositionEmbedder()
            ])
        self.preprocessing_pipeline = preprocessing_pipeline

        if matching_pipeline is None:
            # Default matching pipeline
            matching_pipeline = self.generate_standard_matching_pipeline()
        self.matching_pipeline = matching_pipeline

        if resource_manager is None:
            resource_manager = ResourceManager()
        self.resource_manager = resource_manager

        if statistics is None:
            statistics = Statistics(do_collect=True)
        self.statistics = statistics

        if logger is None:
            logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            logger = logging.getLogger()
        self.logger = logger

        self.random_seeds = [794009, 287762, 880883, 663238, 137616, 543468, 329177, 322737, 343909, 824474, 220481,
                             832096, 962731, 345784, 317557, 696622, 675696, 467273, 475463, 540128]

    @classmethod
    def generate_standard_matching_pipeline(cls, settings: Dict[str, Any] = None) -> Pipeline:
        """
        Generate a standard matching pipeline, with the possibility to override basic settings
        :param settings: Custom settings
        :return: the generated pipeline
        """
        predefined_settings: Dict[str, Any] = {
            "max_num_feedback": 25,
            "len_ranked_list": 10,
            "max_distance": 0.2,
            "num_random_docs": 1,
            "num_bad_docs": 0,
            "num_recent_docs": 0,
            "sampling_mode": "AT_MAX_DISTANCE_THRESHOLD",
            "adjust_threshold": True,
            "additional_nuggets_extractor": DummyCustomMatchExtractor(),
            "store_best_guesses": True,
        }

        if settings is not None:
            predefined_settings.update(settings)

        return Pipeline(
            [
                SplitAttributeNameLabelParaphraser(do_lowercase=True, splitters=[" ", "_"]),
                ContextSentenceCacher(),
                SBERTLabelEmbedder("SBERTBertLargeNliMeanTokensResource"),
                SBERTDocumentSentenceEmbedder("SBERTBertLargeNliMeanTokensResource"),
                RankingBasedMatcher(
                    distance=SignalsMeanDistance(
                        signal_identifiers=[
                            "LabelEmbeddingSignal",
                            "TextEmbeddingSignal",
                            "ContextSentenceEmbeddingSignal",
                            "RelativePositionSignal"
                        ]
                    ),
                    max_num_feedback=predefined_settings["max_num_feedback"],
                    len_ranked_list=predefined_settings["len_ranked_list"],
                    max_distance=predefined_settings["max_distance"],
                    num_random_docs=predefined_settings["num_random_docs"],
                    num_bad_docs=predefined_settings["num_bad_docs"],
                    num_recent_docs=predefined_settings["num_recent_docs"],
                    sampling_mode=predefined_settings["sampling_mode"],
                    adjust_threshold=predefined_settings["adjust_threshold"],
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
                    find_additional_nuggets=predefined_settings["additional_nuggets_extractor"],
                    store_best_guesses=predefined_settings["store_best_guesses"],
                )
            ]
        )

    def preprocess(self):
        pass

    def fill(self, raw_attributes: Optional[List[str]] = None, num_runs: int = 1,
             feedback_oracle: BaseInteractionCallback = None):
        """
        Run real matching
        :param raw_attributes: List of attributes to fill
        :param num_runs: Number of runs (with different random seeds), max 20
        :param feedback_oracle: Oracle for feedback, if None, AutomaticCustomMatchesRandomRankingBasedMatchingFeedback will be used
        """
        # Restrict to 20 runs max (that's also the length of the seed list)
        num_runs = min(num_runs, 20)
        self.last_num_runs = num_runs

        self.logger.setLevel(logging.INFO)

        if feedback_oracle is None:
            feedback_oracle = AutomaticCustomMatchesRandomRankingBasedMatchingFeedback

        run_times = []
        for run, random_seed in enumerate(self.random_seeds[:num_runs]):
            self.logger.info(f"Executing run {run + 1}/{num_runs}.")

            # Load the document base from file to reset the state
            with(open(os.path.join(self.tmp_dir, "tmp_exp_document_base.bson"), "rb")) as file:
                self.document_base = DocumentBase.from_bson(file.read())

            # Set new attributes
            if raw_attributes is not None:
                self.document_base._attributes = [Attribute(a) for a in raw_attributes]

            # Reset existing matches
            for document in self.document_base.documents:
                document._attribute_mappings = dict()
                for attribute in self.document_base.attributes:
                    document._attribute_mappings[attribute] = []
                    self.statistics["matching"]["results"]["considered_as_match"][attribute.name] = set()

            self.statistics["matching"]["config"] = self.matching_pipeline.to_config()

            # set the random seed
            random.seed(random_seed)

            # Logging
            self.logger.setLevel(logging.WARN)
            t0 = time.time()

            # Run the actual matching (including automatic feedback)
            self.matching_pipeline(
                document_base=self.document_base,
                interaction_callback=feedback_oracle(
                    self.ground_truth_docs,
                    self.user_attribute_name2attribute_name
                ),
                status_callback=EmptyStatusCallback(),
                statistics=self.statistics["matching"]["runs"][str(run)]
            )

            self.logger.setLevel(logging.INFO)
            t1 = time.time()
            run_times.append(t1 - t0)
            self.logger.info(f"Finished run {run + 1} in {t1 - t0} seconds.")

    def evaluate(self):
        self.logger.info(f"Evaluating results for last experiment ({self.last_num_runs} runs)")
        interaction_results = {}
        for attribute in self.document_base._attributes:
            attr = attribute.name
            for run in range(self.last_num_runs):
                interaction_results[attr] = []
                best_guesses_for_attr = self.statistics["matching"]["runs"][str(run)]["pipeline-element-4"][attr][
                    "best_guesses"]
                for i, (interaction_count, best_guesses) in enumerate(best_guesses_for_attr):
                    results = self.statistics["matching"]["runs"][str(run)]["results"][attr]["interactions"][i]
                    results["num_should_be_filled_is_empty"] = 0
                    results["num_should_be_filled_is_correct"] = 0
                    results["num_should_be_filled_is_incorrect"] = 0
                    results["num_should_be_empty_is_empty"] = 0
                    results["num_should_be_empty_is_full"] = 0
                    results["correct_nugget_sources"] = Counter()
                    for bg, doc in zip(best_guesses, self.document_base.documents):
                        if len(doc.attribute_mappings[attr]) > 0:
                            if bg is not None:
                                bg_text, bg_doc_name, bg_start, bg_end, bg_source = bg
                                assert doc.name == bg_doc_name
                                if consider_overlap_as_match(bg_start, bg_end,
                                                             doc.attribute_mappings[attr][0].start_char,
                                                             doc.attribute_mappings[attr][0].end_char):
                                    results["num_should_be_filled_is_correct"] += 1
                                    results["correct_nugget_sources"][bg_source] += 1
                                else:
                                    results["num_should_be_filled_is_incorrect"] += 1
                            else:
                                results["num_should_be_filled_is_empty"] += 1
                        else:
                            if bg is None:
                                results["num_should_be_empty_is_empty"] += 1
                            else:
                                results["num_should_be_empty_is_full"] += 1
                    calculate_f1_scores(results)
                    # self.logger.info(f"{attr} - Run {run} - Interaction {interaction_count} => F1: {results['f1_score']}, Sources: {results['correct_nugget_sources']}")
                f1_for_all_interactions = [
                    self.statistics["matching"]["runs"][str(run)]["results"][attr]["interactions"][interaction_count][
                        "f1_score"] for
                    interaction_count in range(i + 1)]
                self.statistics["matching"]["runs"][str(run)]["results"][attr]["f1_scores"] = f1_for_all_interactions
            # Average the different f1 scores for the different runs
            mean_f1_scores = self.statistics["matching"]["results"][attr]["f1_scores"] = [
                sum(values) / self.last_num_runs for values in zip(*[
                    self.statistics["matching"]["runs"][str(run)]["results"][attr]["f1_scores"] for run in
                    range(self.last_num_runs)])]
            self.logger.info(f"Mean F1 scores for '{attr}': {mean_f1_scores}")

    def store_results(self, path: str):
        """
        Store the results of the last experiment in a file
        """
        # Create directories if necessary
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Store the statistics in file
        with(open(path, "w")) as file:
            json.dump(self.statistics.to_serializable(), file, indent=4)
        self.logger.info(f"Stored results of last experiment in '{path}'")

    def run_full_experiment(self, store_preprocessed: bool = True, results_file_path: str = ""):
        self.preprocess()
        # TODO extend, make sure intermediate results are really stored
        self.fill()
        # TODO Evaluate results of the runs
        self.evaluate()
        if results_file_path != "":
            self.store_results(results_file_path)


if __name__ == "__main__":
    from wannadb.matching.custom_match_extraction import FaissSentenceSimilarityExtractor
    from datasets.aviation import aviation as dataset

    with open("../datasets/aviation/aviation5.bson", "rb") as file:
        document_base = DocumentBase.from_bson(file.read())

    ground_truth_documents = documents = dataset.load_dataset()
    user_attribute_names = dataset.ATTRIBUTES
    user_attribute_name2attribute_name = {
        u_attr_name: attr_name for u_attr_name, attr_name in zip(user_attribute_names, dataset.ATTRIBUTES)
    }

    with ResourceManager() as resource_manager:
        extractor = FaissSentenceSimilarityExtractor(num_similar_sentences=10, num_phrases_per_sentence=3)
        raw_attributes = ['event_date', 'airport_code']

        experiment_runner = ExperimentRunner(document_base, ground_truth_documents,
                                             user_attribute_name2attribute_name=user_attribute_name2attribute_name,
                                             matching_pipeline=ExperimentRunner.generate_standard_matching_pipeline(
                                                 {"additional_nuggets_extractor": extractor, "num_recent_docs": 5,
                                                  "num_bad_docs": 3, "len_ranked_list": 12, "max_num_feedback": 40}),
                                             resource_manager=resource_manager)
        experiment_runner.fill(raw_attributes=raw_attributes, num_runs=3)
        experiment_runner.evaluate()
        experiment_runner.store_results(os.path.join("results", f"{'aviation'}_{'faiss'}_{time.strftime('%Y%m%d-%H%M')}.json"))

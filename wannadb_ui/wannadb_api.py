import csv
import glob
import json
import logging
import pathlib
import traceback

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from bson import InvalidBSON

from wannadb.configuration import Pipeline
from wannadb.data.data import Attribute, Document, DocumentBase
from wannadb.interaction import EmptyInteractionCallback, InteractionCallback
from wannadb.matching.custom_match_extraction import FaissSentenceSimilarityExtractor
from wannadb.matching.distance import SignalsMeanDistance
from wannadb.matching.matching import RankingBasedMatcher
from wannadb.preprocessing.dimension_reduction import PCAReducer, TSNEReducer
from wannadb.preprocessing.embedding import BERTContextSentenceEmbedder, RelativePositionEmbedder, \
    SBERTTextEmbedder, SBERTLabelEmbedder, SBERTDocumentSentenceEmbedder
from wannadb.preprocessing.extraction import StanzaNERExtractor, SpacyNERExtractor
from wannadb.preprocessing.label_paraphrasing import OntoNotesLabelParaphraser, \
    SplitAttributeNameLabelParaphraser
from wannadb.preprocessing.normalization import CopyNormalizer
from wannadb.preprocessing.other_processing import ContextSentenceCacher, DuplicatedNuggetsCleaner
from wannadb.statistics import Statistics
from wannadb.status import StatusCallback
from wannadb_parsql.cache_db import SQLiteCacheDB
from wannadb_ui.common import INPUT_DOCS_COLUMN_NAME

logger = logging.getLogger(__name__)


class WannaDBAPI(QObject):

    def __init__(self, feedback_mutex, feedback_cond):
        super(WannaDBAPI, self).__init__()
        self.feedback = None
        self.feedback_mutex = feedback_mutex
        self.feedback_cond = feedback_cond
        self.cache_db = None
        logger.info("Initialized WannaDBAPI.")

    def _reset_cache_db(self):
        logger.info("Reset cache db")
        if self.cache_db is not None:
            self.cache_db.conn.close()
            self.cache_db = None
        self.cache_db = SQLiteCacheDB(db_file=":memory:")
        self.cache_db_to_ui.emit(self.cache_db)

    def _handle_exception(self, exception):
        traceback.print_exception(exception)
        logger.error(str(exception))
        self.error.emit(str(exception))

    ######################################
    # signals (wannadb api --> wannadb ui)
    ######################################
    status = pyqtSignal(str, float)  # message, progress
    finished = pyqtSignal(str)  # message
    error = pyqtSignal(str)  # message
    document_base_to_ui = pyqtSignal(DocumentBase)  # document base
    statistics_to_ui = pyqtSignal(Statistics)  # statistics
    feedback_request_to_ui = pyqtSignal(dict)  # feedback request
    cache_db_to_ui = pyqtSignal(SQLiteCacheDB)  # cached database

    ####################################
    # slots (wannadb ui --> wannadb api)
    ####################################
    @pyqtSlot(str, list, Statistics)
    def create_document_base(self, path, attribute_names, statistics):
        logger.debug("Called slot 'create_document_base'.")
        self.status.emit("Creating document base...", -1)
        try:
            if path == "":
                logger.error("The path cannot be empty!")
                self.error.emit("The path cannot be empty!")
                return

            if pathlib.Path(path).is_dir():
                path += "/*.txt"

            file_paths = glob.glob(path)
            documents = []
            for file_path in file_paths:
                with open(file_path, encoding="utf-8") as file:
                    documents.append(Document(file_path, file.read()))

            if len(set(attribute_names)) != len(attribute_names):
                logger.error("Attribute names must be unique!")
                self.error.emit("Attribute names must be unique!")
                return

            for attribute_name in attribute_names:
                if attribute_name == "":
                    logger.error("Attribute names cannot be empty!")
                    self.error.emit("Attribute names cannot be empty!")
                    return

            self._reset_cache_db()

            attributes = []
            for attribute_name in attribute_names:
                attributes.append(Attribute(attribute_name))
                self.cache_db.create_table_by_name(attribute_name)

            document_base = DocumentBase(documents, attributes)
            self.cache_db.create_input_docs_table(INPUT_DOCS_COLUMN_NAME, document_base.documents)

            if not document_base.validate_consistency():
                logger.error("Document base is inconsistent!")
                self.error.emit("Document base is inconsistent!")
                return

            # load default preprocessing phase
            self.status.emit("Loading preprocessing phase...", -1)

            preprocessing_phase = Pipeline([
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
                RelativePositionEmbedder(),
                DuplicatedNuggetsCleaner(),
                PCAReducer(),
                #TSNEReducer()
            ])

            # run preprocessing phase
            def status_callback_fn(message, progress):
                self.status.emit(message, progress)

            status_callback = StatusCallback(status_callback_fn)

            preprocessing_phase(document_base, EmptyInteractionCallback(), status_callback, statistics)

            self.document_base_to_ui.emit(document_base)
            self.statistics_to_ui.emit(statistics)
            self.finished.emit("Finished!")
        except FileNotFoundError:
            logger.error("Directory does not exist!")
            self.error.emit("Directory does not exist!")
        except Exception as e:
            self._handle_exception(e)

    @pyqtSlot(str)
    def load_document_base_from_bson(self, path):
        logger.debug("Called slot 'load_document_base_from_bson'.")
        self.status.emit("Loading document base from BSON...", -1)
        try:
            with open(path, "rb") as file:
                document_base = DocumentBase.from_bson(file.read())

                if not document_base.validate_consistency():
                    logger.error("Document base is inconsistent!")
                    self.error.emit("Document base is inconsistent!")
                    return

                self._reset_cache_db()
                for attribute in document_base.attributes:
                    self.cache_db.create_table_by_name(attribute.name)
                self.cache_db.create_input_docs_table(INPUT_DOCS_COLUMN_NAME, document_base.documents)

                self.document_base_to_ui.emit(document_base)
                self.finished.emit("Finished!")
        except FileNotFoundError:
            logger.error("File does not exist!")
            self.error.emit("File does not exist!")
        except InvalidBSON:
            logger.error("Unable to decode file!")
            self.error.emit("Unable to decode file!")
        except Exception as e:
            self._handle_exception(e)

    @pyqtSlot(str, DocumentBase)
    def save_document_base_to_bson(self, path, document_base):
        logger.debug("Called slot 'save_document_base_to_bson'.")
        self.status.emit("Saving document base to BSON...", -1)
        try:
            with open(path, "wb") as file:
                file.write(document_base.to_bson())
                self.document_base_to_ui.emit(document_base)
                self.finished.emit("Finished!")
        except FileNotFoundError:
            logger.error("Directory does not exist!")
            self.error.emit("Directory does not exist!")
        except Exception as e:
            self._handle_exception(e)

    @pyqtSlot(str, DocumentBase)
    def save_table_to_csv(self, path, document_base):
        logger.debug("Called slot 'save_table_to_csv'.")
        self.status.emit("Saving table to CSV...", -1)
        try:
            # check that the table is complete
            for attribute in document_base.attributes:
                for document in document_base.documents:
                    if attribute.name not in document.attribute_mappings.keys():
                        logger.error("Cannot save a table with unpopulated attributes!")
                        self.error.emit("Cannot save a table with unpopulated attributes!")
                        return

            # TODO: currently stores the text of the first matching nugget (if there is one)
            table_dict = document_base.to_table_dict("text")
            headers = list(table_dict.keys())
            rows = []
            for ix in range(len(table_dict[headers[0]])):
                row = []
                for header in headers:
                    if header == "document-name":
                        row.append(table_dict[header][ix])
                    elif table_dict[header][ix] == []:
                        row.append(None)
                    else:
                        row.append(table_dict[header][ix][0])
                rows.append(row)
            with open(path, "w", encoding="utf-8", newline="") as file:
                writer = csv.writer(file, delimiter=",", quotechar='"', quoting=csv.QUOTE_ALL)
                writer.writerow(headers)
                writer.writerows(rows)
            self.document_base_to_ui.emit(document_base)
            self.finished.emit("Finished!")
        except FileNotFoundError:
            logger.error("Directory does not exist!")
            self.error.emit("Directory does not exist!")
        except Exception as e:
            self._handle_exception(e)

    @pyqtSlot(str, DocumentBase)
    def add_attribute(self, name, document_base):
        logger.debug("Called slot 'add_attribute'.")
        self.status.emit("Adding attribute...", -1)
        try:
            if name in [attribute.name for attribute in document_base.attributes]:
                logger.error("Attribute name already exists!")
                self.error.emit("Attribute name already exists!")
            elif name == "":
                logger.error("Attribute name must not be empty!")
                self.error.emit("Attribute name must not be empty!")
            else:
                document_base.attributes.append(Attribute(name))
                self.cache_db.create_table_by_name(name)
                self.document_base_to_ui.emit(document_base)
                self.finished.emit("Finished!")
        except Exception as e:
            self._handle_exception(e)

    @pyqtSlot(list, DocumentBase)
    def add_attributes(self, names, document_base):
        logger.debug("Called slot 'add_attributes'.")
        self.status.emit("Adding attributes...", -1)
        try:
            already_existing_names = []
            for name in names:
                if name in [attribute.name for attribute in document_base.attributes]:
                    logger.info(f"Attribute name '{name}' already exists and was thus not added.")
                    already_existing_names.append(name)
                elif name == "":
                    logger.info("Attribute name must not be empty and was thus ignored.")
                else:
                    document_base.attributes.append(Attribute(name))
                    self.cache_db.create_table_by_name(name)
            self.document_base_to_ui.emit(document_base)
            self.finished.emit("Finished!")
        except Exception as e:
            self._handle_exception(e)

    @pyqtSlot(str, DocumentBase)
    def remove_attribute(self, name, document_base):
        logger.debug("Called slot 'remove_attribute'.")
        self.status.emit("Removing attribute...", -1)
        self.cache_db.delete_table(name)
        try:
            if name in [attribute.name for attribute in document_base.attributes]:
                for document in document_base.documents:
                    if name in document.attribute_mappings.keys():
                        del document.attribute_mappings[name]

                for attribute in document_base.attributes:
                    if attribute.name == name:
                        document_base.attributes.remove(attribute)
                        break
                self.document_base_to_ui.emit(document_base)
                self.finished.emit("Finished!")
            else:
                logger.error("Attribute name does not exist!")
                self.error.emit("Attribute name does not exist!")
        except Exception as e:
            self._handle_exception(e)

    @pyqtSlot(str, DocumentBase)
    def forget_matches_for_attribute(self, name, document_base):
        logger.debug("Called slot 'forget_matches_for_attribute'.")
        self.status.emit("Forgetting matches...", -1)
        self.cache_db.delete_table(name)
        try:
            if name in [attribute.name for attribute in document_base.attributes]:
                for document in document_base.documents:
                    if name in document.attribute_mappings.keys():
                        del document.attribute_mappings[name]
                self.cache_db.create_table_by_name(name)
                self.document_base_to_ui.emit(document_base)
                self.finished.emit("Finished!")
            else:
                logger.error("Attribute name does not exist!")
                self.error.emit("Attribute name does not exist!")
        except Exception as e:
            self._handle_exception(e)

    @pyqtSlot(DocumentBase)
    def forget_matches(self, document_base):
        logger.debug("Called slot 'forget_matches'.")
        self.status.emit("Forgetting matches...", -1)
        for attribute in document_base.attributes:
            self.cache_db.delete_table(attribute.name)
            self.cache_db.create_table_by_name(attribute.name)
        try:
            for document in document_base.documents:
                document.attribute_mappings.clear()
            self.document_base_to_ui.emit(document_base)
            self.finished.emit("Finished!")
        except Exception as e:
            self._handle_exception(e)

    @pyqtSlot(str, Statistics)
    def save_statistics_to_json(self, path, statistics):
        logger.debug("Called slot 'save_statistics_to_json'.")
        self.status.emit("Saving statistics to JSON...", -1)
        try:
            with open(path, "w", encoding="utf-8") as file:
                json.dump(statistics.to_serializable(), file, indent=2)
                self.finished.emit("Finished!")
        except FileNotFoundError:
            logger.error("Directory does not exist!")
            self.error.emit("Directory does not exist!")
        except Exception as e:
            self._handle_exception(e)

    @pyqtSlot(DocumentBase, Statistics)
    def interactive_table_population(self, document_base, statistics):
        logger.debug("Called slot 'interactive_table_population'.")
        try:
            # load default matching phase
            self.status.emit("Loading matching phase...", -1)

            matching_phase = Pipeline(
                [
                    SplitAttributeNameLabelParaphraser(do_lowercase=True, splitters=[" ", "_"]),
                    ContextSentenceCacher(),
                    SBERTLabelEmbedder("SBERTBertLargeNliMeanTokensResource"),
                    SBERTDocumentSentenceEmbedder("SBERTBertLargeNliMeanTokensResource"),
                    PCAReducer(),
                    #TSNEReducer(),
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
                                RelativePositionEmbedder(),
                                PCAReducer(),
                                #TSNEReducer()
                            ]
                        ),
                        find_additional_nuggets=FaissSentenceSimilarityExtractor(num_similar_sentences=20, num_phrases_per_sentence=3),
                        store_best_guesses=True,
                    )
                ]
            )

            # run matching phase
            def status_callback_fn(message, progress):
                self.status.emit(message, progress)

            status_callback = StatusCallback(status_callback_fn)

            def interaction_callback_fn(pipeline_element_identifier, feedback_request):
                feedback_request["identifier"] = pipeline_element_identifier
                self.feedback_request_to_ui.emit(feedback_request)

                self.feedback_mutex.lock()
                try:
                    self.feedback_cond.wait(self.feedback_mutex)
                finally:
                    self.feedback_mutex.unlock()

                return self.feedback

            interaction_callback = InteractionCallback(interaction_callback_fn)

            matching_phase(document_base, interaction_callback, status_callback, statistics)

            self.document_base_to_ui.emit(document_base)
            self.statistics_to_ui.emit(statistics)
            self.finished.emit("Finished!")
        except Exception as e:
            self._handle_exception(e)

import enum
import logging
import re
import wannadb_ui.visualizations as visualizations

from PyQt6.QtCore import QMutex, Qt, QThread, QWaitCondition, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMainWindow, QProgressBar, QWidget, QInputDialog

from wannadb.data.data import DocumentBase
from wannadb.statistics import Statistics
from wannadb_parsql.cache_db import SQLiteCacheDB
from wannadb_ui.common import MENU_FONT, STATUS_BAR_FONT, STATUS_BAR_FONT_BOLD, RED, BLACK, show_confirmation_dialog
from wannadb_ui.document_base import DocumentBaseCreatorWidget, DocumentBaseViewerWidget, DocumentBaseCreatingWidget
from wannadb_ui.interactive_matching import InteractiveMatchingWidget
from wannadb_ui.start_menu import StartMenuWidget
from wannadb_ui.wannadb_api import WannaDBAPI

logger = logging.getLogger(__name__)


class ApplicationState(enum.Enum):
    """
    begins with START

    START --> CREATE_DOCUMENT_BASE, BUSY_STATE
    CREATE_DOCUMENT_BASE --> START, CREATING_DOCUMENT_BASE
    BUSY_STATE --> START, VIEW_DOCUMENT_BASE
    CREATING_DOCUMENT_BASE --> START, VIEW_DOCUMENT_BASE
    VIEW_DOCUMENT_BASE --> START, BUSY_STATE, LOAD_DOCUMENT_BASE, CREATE_DOCUMENT_BASE
    INTERACTIVE_MATCHING --> VIEW_DOCUMENT_BASE
    """
    START = "start"
    CREATE_DOCUMENT_BASE = "create_document_base"
    BUSY = "busy"
    CREATING_DOCUMENT_BASE = "creating_document_base"
    VIEW_DOCUMENT_BASE = "view_document_base"
    INTERACTIVE_MATCHING = "interactive_matching"


class MainWindow(QMainWindow):
    ######################################
    # signals (wannadb ui --> wannadb api)
    ######################################
    create_document_base = pyqtSignal(str, list, Statistics)
    add_attribute = pyqtSignal(str, DocumentBase)
    add_attributes = pyqtSignal(list, DocumentBase)
    remove_attribute = pyqtSignal(str, DocumentBase)
    forget_matches_for_attribute = pyqtSignal(str, DocumentBase)
    load_document_base_from_bson = pyqtSignal(str)
    save_document_base_to_bson = pyqtSignal(str, DocumentBase)
    save_table_to_csv = pyqtSignal(str, DocumentBase)
    forget_matches = pyqtSignal(DocumentBase)
    save_statistics_to_json = pyqtSignal(str, Statistics)
    interactive_table_population = pyqtSignal(DocumentBase, Statistics)

    ####################################
    # slots (wannadb api --> wannadb ui)
    ####################################
    @pyqtSlot(str, float)
    def status(self, message, progress):
        logger.debug("Called slot 'status'.")

        self.status_widget_message.setFont(STATUS_BAR_FONT)
        self.status_widget_message.setStyleSheet(f"color: {BLACK}")
        self.status_widget_message.setText(message)
        if progress == -1:
            self.status_widget_progress.setRange(0, 0)
        else:
            self.status_widget_progress.setRange(0, 100)
            self.status_widget_progress.setValue(int(progress * 100))

    @pyqtSlot(str)
    def finished(self, message):
        logger.debug("Called slot 'finished'.")

        self.status_widget_message.setText(message)
        self.status_widget_progress.setRange(0, 100)
        self.status_widget_progress.setValue(100)

    @pyqtSlot(str)
    def error(self, message):
        logger.debug("Called slot 'error'.")

        self.status_widget_message.setFont(STATUS_BAR_FONT_BOLD)
        self.status_widget_message.setStyleSheet(f"color: {RED}")
        self.status_widget_message.setText(message)
        self.status_widget_progress.setRange(0, 100)
        self.status_widget_progress.setValue(0)

        if self.document_base is not None:
            self.to_view_document_base_state()
        else:
            self.to_start_state()

    @pyqtSlot(DocumentBase)
    def document_base_to_ui(self, document_base):
        logger.debug("Called slot 'document_base_to_ui'.")

        self.document_base = document_base
        self.document_base_viewer_widget.update_document_base(self.document_base)

        self.to_view_document_base_state()

    @pyqtSlot(Statistics)
    def statistics_to_ui(self, statistics):
        logger.debug("Called slot 'statistics_to_ui'.")

        self.statistics = statistics

    @pyqtSlot(SQLiteCacheDB)
    def cache_db_to_ui(self, cache_db):
        logger.debug("Called slot 'cache_db_to_ui'.")
        logger.debug("Set new cached db")
        self.cache_db = cache_db

    @pyqtSlot(dict)
    def feedback_request_to_ui(self, feedback_request):
        logger.debug("Called slot 'feedback_request_to_ui'.")

        if "do-attribute-request" in feedback_request.keys():
            if self.attributes_to_match is None or feedback_request["attribute"].name in self.attributes_to_match:
                self.give_feedback_task({
                    "do-attribute": True
                })
            else:
                self.give_feedback_task({
                    "do-attribute": False
                })
        else:
            self.status_widget_message.setText("Waiting for feedback.")
            self.status_widget_progress.setRange(0, 100)
            self.status_widget_progress.setValue(100)

            self.interactive_matching_widget.handle_feedback_request(feedback_request)

    #######
    # tasks
    #######
    def load_document_base_from_bson_task(self):
        logger.info("Execute task 'load_document_base_from_bson_task'.")

        if self.document_base is not None:
            confirmed = show_confirmation_dialog(self, "Discard document base?",
                                                 "Loading a different document base will discard the current document base.",
                                                 "Yes, discard document base.", "No, keep document base.")
        else:
            confirmed = True
        if confirmed:
            path, ok = QFileDialog.getOpenFileName(self, "Choose a document collection .bson file!")
            if ok:
                self.to_busy_state()
                # noinspection PyUnresolvedReferences
                self.load_document_base_from_bson.emit(str(path))

    def save_document_base_to_bson_task(self):
        logger.info("Execute task 'save_document_base_to_bson_task'.")

        if self.document_base is not None:
            path, ok = QFileDialog.getSaveFileName(self, "Choose where to save the document collection .bson file!")
            if ok:
                self.to_busy_state()
                # noinspection PyUnresolvedReferences
                self.save_document_base_to_bson.emit(str(path), self.document_base)

    def add_attribute_task(self):
        logger.info("Execute task 'add_attribute_task'.")

        if self.document_base is not None:
            name, ok = QInputDialog.getText(self, "Create Attribute", "Attribute name:")
            name = re.sub(r"\s+", "_", name)
            if ok:
                self.to_busy_state()
                # noinspection PyUnresolvedReferences
                self.add_attribute.emit(str(name), self.document_base)

    def remove_attribute_task(self):
        logger.info("Execute task 'remove_attribute_task'.")

        if self.document_base is not None:
            name, ok = QInputDialog.getText(self, "Remove Attribute", "Attribute name:")
            if ok:
                self.to_busy_state()
                # noinspection PyUnresolvedReferences
                self.remove_attribute.emit(str(name), self.document_base)

    def remove_attribute_with_given_name_task(self, attribute_name):
        logger.info("Execute task 'remove_attribute_with_given_name_task'.")

        if self.document_base is not None:
            self.to_busy_state()
            # noinspection PyUnresolvedReferences
            self.remove_attribute.emit(str(attribute_name), self.document_base)

    def forget_matches_for_attribute_task(self):
        logger.info("Execute task 'forget_matches_for_attribute_task'.")

        if self.document_base is not None:
            name, ok = QInputDialog.getText(self, "Forget Matches for Attribute", "Attribute name:")
            if ok:
                self.to_busy_state()
                # noinspection PyUnresolvedReferences
                self.forget_matches_for_attribute.emit(str(name), self.document_base)

    def forget_matches_for_attribute_with_given_name_task(self, attribute_name):
        logger.info("Execute task 'forget_matches_for_attribute_with_given_name_task'.")

        if self.document_base is not None:
            self.to_busy_state()
            # noinspection PyUnresolvedReferences
            self.forget_matches_for_attribute.emit(attribute_name, self.document_base)

    def forget_matches_task(self):
        logger.info("Execute task 'forget_matches_task'.")

        if self.document_base is not None:
            self.to_busy_state()
            # noinspection PyUnresolvedReferences
            self.forget_matches.emit(self.document_base)

    def enable_collect_statistics_task(self):
        logger.info("Execute task 'task_enable_collect_statistics'.")

        self.collect_statistics = True

    def disable_collect_statistics_task(self):
        logger.info("Execute task 'disable_collect_statistics_task'.")

        self.collect_statistics = False

    def save_statistics_to_json_task(self):
        logger.info("Execute task 'save_statistics_to_json_task'.")

        if self.statistics is not None:
            path = str(QFileDialog.getSaveFileName(self, "Choose where to save the statistics .json file!")[0])
            if path != "":
                self.to_busy_state()
                # noinspection PyUnresolvedReferences
                self.save_statistics_to_json.emit(path, self.statistics)

    def enable_visualizations_task(self):
        logger.info("Execute task 'enable_visualizations_task'.")

        self.visualizations = True

        self.interactive_matching_widget.enable_visualizations()
        self.enable_visualizations_action.setEnabled(False)
        self.disable_visualizations_action.setEnabled(True)

    def disable_visualizations_task(self):
        logger.info("Execute task 'disable_visualizations_task'.")

        self.visualizations = False

        self.interactive_matching_widget.disable_visualizations()
        self.enable_visualizations_action.setEnabled(True)
        self.disable_visualizations_action.setEnabled(False)

    def enable_accessible_color_palette_task(self):
        logger.info("Execute task 'enable_accessible_color_palette_task'.")
        self.accessible_color_palette = True
        self.interactive_matching_widget.enable_accessible_color_palette()
        self.enable_accessible_color_palette_action.setEnabled(False)
        self.disable_accessible_color_palette_action.setEnabled(True)
        
    def disable_accessible_color_palette_task(self):
        logger.info("Execute task 'disable_accessible_color_palette_task'.")
        self.accessible_color_palette = False
        self.interactive_matching_widget.disable_accessible_color_palette()
        self.enable_accessible_color_palette_action.setEnabled(True)
        self.disable_accessible_color_palette_action.setEnabled(False)
       
    def show_document_base_creator_widget_task(self):
        logger.info("Execute task 'show_document_base_creator_widget_task'.")

        if self.document_base is not None:
            confirmed = show_confirmation_dialog(self, "Discard document base?",
                                                 "Creating a new document base will discard the current document base.",
                                                 "Yes, discard document base.", "No, keep document base.")
        else:
            confirmed = True
        if confirmed:
            self.to_create_document_base_state()

    def create_document_base_task(self, path, attribute_names):
        logger.info("Execute task 'create_document_base_task'.")

        attribute_names = [re.sub(r"\s+", "_", name) for name in attribute_names]

        self.statistics = Statistics(self.collect_statistics)

        self.to_creating_document_base_state()

        # noinspection PyUnresolvedReferences
        self.create_document_base.emit(path, attribute_names, self.statistics)

    def save_table_to_csv_task(self):
        logger.info("Execute task 'save_table_to_csv_task'.")

        if self.document_base is not None:
            path = str(QFileDialog.getSaveFileName(self, "Choose where to save the table .csv file!")[0])
            if path != "":
                self.to_busy_state()
                # noinspection PyUnresolvedReferences
                self.save_table_to_csv.emit(path, self.document_base)

    def give_feedback_task(self, feedback):
        logger.info("Execute task 'give_feedback_task'.")

        self.status_widget_message.setText("Processing feedback.")
        self.status_widget_progress.setRange(0, 0)

        self.disable_global_input()
        self.api.feedback = feedback
        self.feedback_cond.wakeAll()

        self._enable_visualization_settings()
        self._enable_color_palette_settings()
    def interactive_table_population_task(self):
        logger.info("Execute task 'interactive_table_population_task'.")

        if self.document_base is not None:
            self.attributes_to_match = None
            self.statistics = Statistics(self.collect_statistics)

            self.to_interactive_matching_state()

            # noinspection PyUnresolvedReferences
            self.interactive_table_population.emit(self.document_base, self.statistics)

    def match_attribute_task(self, attribute_name):
        logger.info("Execute task 'match_attribute_task'.")

        if self.document_base is not None:
            self.attributes_to_match = [attribute_name]
            self.statistics = Statistics(self.collect_statistics)

            self.to_interactive_matching_state()

            # noinspection PyUnresolvedReferences
            self.interactive_table_population.emit(self.document_base, self.statistics)

    ##################
    # controller logic
    ##################

    def disable_global_input(self):
        for action in self._all_actions:
            action.setEnabled(False)

        self.start_menu_widget.disable_input()
        self.document_base_creator_widget.disable_input()
        self.document_base_viewer_widget.disable_input()
        self.interactive_matching_widget.disable_input()

    def to_start_state(self):
        logger.info("To START state.")
        self.application_state = ApplicationState.START
        self.document_base = None

        self.disable_global_input()
        self.show_document_base_creator_widget_action.setEnabled(True)
        self.load_document_base_from_bson_action.setEnabled(True)
        self.start_menu_widget.enable_input()

        if self.statistics is not None:
            self.save_statistics_to_json_action.setEnabled(True)
        if self.collect_statistics:
            self.disable_collect_statistics_action.setEnabled(True)
        else:
            self.enable_collect_statistics_action.setEnabled(True)

        self._enable_visualization_settings()
        self._enable_color_palette_settings()
        self.central_widget_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.document_base_viewer_widget.hide()
        self.document_base_creator_widget.hide()
        self.document_base_creation_widget.hide()
        self.interactive_matching_widget.hide()

        self.central_widget_layout.removeWidget(self.document_base_viewer_widget)
        self.central_widget_layout.removeWidget(self.document_base_creator_widget)
        self.central_widget_layout.removeWidget(self.document_base_creation_widget)
        self.central_widget_layout.removeWidget(self.interactive_matching_widget)
        self.central_widget_layout.addWidget(self.start_menu_widget)
        self.start_menu_widget.show()
        self.central_widget_layout.update()

    def to_create_document_base_state(self):
        logger.info("To CREATE_DOCUMENT_BASE state.")
        self.application_state = ApplicationState.CREATE_DOCUMENT_BASE
        self.document_base = None

        self.document_base_creator_widget.initialize_for_new_document_base()

        self.disable_global_input()
        self.document_base_creator_widget.enable_input()

        if self.statistics is not None:
            self.save_statistics_to_json_action.setEnabled(True)
        if self.collect_statistics:
            self.disable_collect_statistics_action.setEnabled(True)
        else:
            self.enable_collect_statistics_action.setEnabled(True)

        self._enable_visualization_settings()
        self._enable_color_palette_settings()
        self.central_widget_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.start_menu_widget.hide()
        self.document_base_creation_widget.hide()
        self.document_base_viewer_widget.hide()
        self.interactive_matching_widget.hide()

        self.central_widget_layout.removeWidget(self.start_menu_widget)
        self.central_widget_layout.removeWidget(self.document_base_viewer_widget)
        self.central_widget_layout.removeWidget(self.document_base_creation_widget)
        self.central_widget_layout.removeWidget(self.interactive_matching_widget)
        self.central_widget_layout.addWidget(self.document_base_creator_widget)
        self.document_base_creator_widget.show()
        self.central_widget_layout.update()

    def to_creating_document_base_state(self):
        logger.info("To CREATING_DOCUMENT_BASE state.")
        self.application_state = ApplicationState.CREATING_DOCUMENT_BASE

        self.disable_global_input()

        self._enable_visualization_settings()
        self._enable_color_palette_settings()
        self.central_widget_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.start_menu_widget.hide()
        self.document_base_creator_widget.hide()
        self.document_base_viewer_widget.hide()
        self.interactive_matching_widget.hide()

        self.central_widget_layout.removeWidget(self.start_menu_widget)
        self.central_widget_layout.removeWidget(self.document_base_viewer_widget)
        self.central_widget_layout.removeWidget(self.document_base_creator_widget)
        self.central_widget_layout.removeWidget(self.interactive_matching_widget)
        self.central_widget_layout.addWidget(self.document_base_creation_widget)
        self.document_base_creation_widget.show()
        self.central_widget_layout.update()

    def to_busy_state(self):
        logger.info("To BUSY state.")
        self.application_state = ApplicationState.BUSY

        self.disable_global_input()
        # the correct widgets are already visible

    def to_view_document_base_state(self):
        logger.info("To VIEW_DOCUMENT_BASE state.")
        self.application_state = ApplicationState.VIEW_DOCUMENT_BASE

        self.disable_global_input()
        self.show_document_base_creator_widget_action.setEnabled(True)
        self.add_attribute_action.setEnabled(True)
        self.remove_attribute_action.setEnabled(True)
        self.forget_matches_for_attribute_action.setEnabled(True)
        self.load_document_base_from_bson_action.setEnabled(True)
        self.save_document_base_to_bson_action.setEnabled(True)
        self.save_table_to_csv_action.setEnabled(True)
        self.forget_matches_action.setEnabled(True)
        self.interactive_table_population_action.setEnabled(True)

        if self.statistics is not None:
            self.save_statistics_to_json_action.setEnabled(True)
        if self.collect_statistics:
            self.disable_collect_statistics_action.setEnabled(True)
        else:
            self.enable_collect_statistics_action.setEnabled(True)

        self._enable_visualization_settings()
        self._enable_color_palette_settings()
        self.document_base_viewer_widget.enable_input()

        self.central_widget_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.start_menu_widget.hide()
        self.document_base_creation_widget.hide()
        self.interactive_matching_widget.hide()
        self.document_base_creator_widget.hide()

        self.central_widget_layout.removeWidget(self.start_menu_widget)
        self.central_widget_layout.removeWidget(self.interactive_matching_widget)
        self.central_widget_layout.removeWidget(self.document_base_creator_widget)
        self.central_widget_layout.removeWidget(self.document_base_creation_widget)
        self.central_widget_layout.addWidget(self.document_base_viewer_widget)
        self.document_base_viewer_widget.show()
        self.central_widget_layout.update()

    def to_interactive_matching_state(self):
        logger.info("To INTERACTIVE_MATCHING state.")
        self.application_state = ApplicationState.INTERACTIVE_MATCHING

        self.disable_global_input()

        if self.statistics is not None:
            self.save_statistics_to_json_action.setEnabled(True)
        if self.collect_statistics:
            self.disable_collect_statistics_action.setEnabled(True)
        else:
            self.enable_collect_statistics_action.setEnabled(True)

        self._enable_visualization_settings()
        self._enable_color_palette_settings()
        self.central_widget_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.start_menu_widget.hide()
        self.document_base_viewer_widget.hide()
        self.document_base_creator_widget.hide()
        self.document_base_creation_widget.hide()

        self.central_widget_layout.removeWidget(self.start_menu_widget)
        self.central_widget_layout.removeWidget(self.document_base_viewer_widget)
        self.central_widget_layout.removeWidget(self.document_base_creator_widget)
        self.central_widget_layout.removeWidget(self.document_base_creation_widget)
        self.central_widget_layout.addWidget(self.interactive_matching_widget)
        self.interactive_matching_widget.show()
        self.central_widget_layout.update()

    def _enable_visualization_settings(self):
        self.enable_visualizations_action.setEnabled(not self.visualizations)
        self.disable_visualizations_action.setEnabled(self.visualizations)

    def _enable_color_palette_settings(self):
        self.enable_accessible_color_palette_action.setEnabled(not self.accessible_color_palette)
        self.disable_accessible_color_palette_action.setEnabled(self.accessible_color_palette)
    # noinspection PyUnresolvedReferences
    def __init__(self) -> None:
        super(MainWindow, self).__init__()
        self.setWindowTitle("WannaDB")

        self.application_state = ApplicationState.START

        self.document_base = None
        self.statistics = None
        self.collect_statistics = True
        self.visualizations = True
        self.accessible_color_palette = False
        self.attributes_to_match = None
        self.cache_db = None

        # set up the api_thread and api and connect slots and signals
        self.feedback_mutex = QMutex()
        self.feedback_cond = QWaitCondition()
        self.api = WannaDBAPI(self.feedback_mutex, self.feedback_cond)
        self.api_thread = QThread()
        self.api.moveToThread(self.api_thread)
        self.create_document_base.connect(self.api.create_document_base)
        self.add_attribute.connect(self.api.add_attribute)
        self.add_attributes.connect(self.api.add_attributes)
        self.remove_attribute.connect(self.api.remove_attribute)
        self.forget_matches_for_attribute.connect(self.api.forget_matches_for_attribute)
        self.load_document_base_from_bson.connect(self.api.load_document_base_from_bson)
        self.save_document_base_to_bson.connect(self.api.save_document_base_to_bson)
        self.save_table_to_csv.connect(self.api.save_table_to_csv)
        self.forget_matches.connect(self.api.forget_matches)
        self.save_statistics_to_json.connect(self.api.save_statistics_to_json)
        self.interactive_table_population.connect(self.api.interactive_table_population)

        self.api.status.connect(self.status)
        self.api.finished.connect(self.finished)
        self.api.error.connect(self.error)
        self.api.document_base_to_ui.connect(self.document_base_to_ui)
        self.api.statistics_to_ui.connect(self.statistics_to_ui)
        self.api.cache_db_to_ui.connect(self.cache_db_to_ui)
        self.api.feedback_request_to_ui.connect(self.feedback_request_to_ui)
        self.api_thread.start()

        # set up the status bar
        self.status_bar = self.statusBar()
        self.status_bar.setFont(STATUS_BAR_FONT)

        self.status_widget = QWidget(self.status_bar)
        self.status_widget_layout = QHBoxLayout(self.status_widget)
        self.status_widget_layout.setContentsMargins(0, 0, 0, 0)
        self.status_widget_message = QLabel()
        self.status_widget_message.setFont(STATUS_BAR_FONT)
        self.status_widget_message.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.status_widget_message.setMinimumWidth(10)
        self.status_widget_layout.addWidget(self.status_widget_message)
        self.status_widget_progress = QProgressBar()
        self.status_widget_progress.setMinimumWidth(10)
        self.status_widget_progress.setMaximumWidth(200)
        self.status_widget_progress.setTextVisible(False)
        self.status_widget_progress.setMaximumHeight(20)
        self.status_widget_layout.addWidget(self.status_widget_progress)
        self.status_bar.addPermanentWidget(self.status_widget)

        # set up the actions
        self._all_actions = []

        self.show_document_base_creator_widget_action = QAction("&Create new document base", self)
        self.show_document_base_creator_widget_action.setIcon(QIcon("wannadb_ui/resources/two_documents.svg"))
        self.show_document_base_creator_widget_action.setStatusTip(
            "Create a new document base from a collection of .txt files and a list of attribute names."
        )
        self.show_document_base_creator_widget_action.triggered.connect(self.show_document_base_creator_widget_task)
        self._all_actions.append(self.show_document_base_creator_widget_action)

        self.add_attribute_action = QAction("&Add attribute", self)
        self.add_attribute_action.setIcon(QIcon("wannadb_ui/resources/plus.svg"))
        self.add_attribute_action.setStatusTip("Add a new attribute to the document base.")
        self.add_attribute_action.triggered.connect(self.add_attribute_task)
        self._all_actions.append(self.add_attribute_action)

        self.remove_attribute_action = QAction("&Remove attribute", self)
        self.remove_attribute_action.setIcon(QIcon("wannadb_ui/resources/trash.svg"))
        self.remove_attribute_action.setStatusTip("Remove an attribute from the document base.")
        self.remove_attribute_action.triggered.connect(self.remove_attribute_task)
        self._all_actions.append(self.remove_attribute_action)

        self.forget_matches_for_attribute_action = QAction("&Clear attribute", self)
        self.forget_matches_for_attribute_action.setIcon(QIcon("wannadb_ui/resources/redo.svg"))
        self.forget_matches_for_attribute_action.setStatusTip("Clear the cells of a single attribute.")
        self.forget_matches_for_attribute_action.triggered.connect(self.forget_matches_for_attribute_task)
        self._all_actions.append(self.forget_matches_for_attribute_action)

        self.load_document_base_from_bson_action = QAction("&Load document base", self)
        self.load_document_base_from_bson_action.setIcon(QIcon("wannadb_ui/resources/folder.svg"))
        self.load_document_base_from_bson_action.setStatusTip("Load an existing document base from a .bson file.")
        self.load_document_base_from_bson_action.triggered.connect(self.load_document_base_from_bson_task)
        self._all_actions.append(self.load_document_base_from_bson_action)

        self.save_document_base_to_bson_action = QAction("&Save document base", self)
        self.save_document_base_to_bson_action.setIcon(QIcon("wannadb_ui/resources/save.svg"))
        self.save_document_base_to_bson_action.setStatusTip("Save the document base in a .bson file.")
        self.save_document_base_to_bson_action.triggered.connect(self.save_document_base_to_bson_task)
        self._all_actions.append(self.save_document_base_to_bson_action)

        self.save_table_to_csv_action = QAction("&Export table to CSV", self)
        self.save_table_to_csv_action.setIcon(QIcon("wannadb_ui/resources/table.svg"))
        self.save_table_to_csv_action.setStatusTip("Save the table to a .csv file.")
        self.save_table_to_csv_action.triggered.connect(self.save_table_to_csv_task)
        self._all_actions.append(self.save_table_to_csv_action)

        self.forget_matches_action = QAction("&Clear all attributes", self)
        self.forget_matches_action.setIcon(QIcon("wannadb_ui/resources/redo.svg"))
        self.forget_matches_action.setStatusTip("Clear the cells of all attributes.")
        self.forget_matches_action.triggered.connect(self.forget_matches_task)
        self._all_actions.append(self.forget_matches_action)

        self.interactive_table_population_action = QAction("&Populate remaining attributes", self)
        self.interactive_table_population_action.setStatusTip("Populate the cells of the remaining attributes.")
        self.interactive_table_population_action.setIcon(QIcon("wannadb_ui/resources/run_run.svg"))
        self.interactive_table_population_action.triggered.connect(self.interactive_table_population_task)
        self._all_actions.append(self.interactive_table_population_action)

        self.enable_collect_statistics_action = QAction("&Enable statistics", self)
        self.enable_collect_statistics_action.setIcon(QIcon("wannadb_ui/resources/statistics.svg"))
        self.enable_collect_statistics_action.setStatusTip("Enable collecting statistics.")
        self.enable_collect_statistics_action.triggered.connect(self.enable_collect_statistics_task)
        self._all_actions.append(self.enable_collect_statistics_action)

        self.disable_collect_statistics_action = QAction("&Disable statistics", self)
        self.disable_collect_statistics_action.setIcon(QIcon("wannadb_ui/resources/statistics_incorrect.svg"))
        self.disable_collect_statistics_action.setStatusTip("Disable collecting statistics.")
        self.disable_collect_statistics_action.triggered.connect(self.disable_collect_statistics_task)
        self._all_actions.append(self.disable_collect_statistics_action)

        self.save_statistics_to_json_action = QAction("&Save statistics", self)
        self.save_statistics_to_json_action.setIcon(QIcon("wannadb_ui/resources/statistics_save.svg"))
        self.save_statistics_to_json_action.setStatusTip("Save the statistics to a .json file.")
        self.save_statistics_to_json_action.triggered.connect(self.save_statistics_to_json_task)
        self._all_actions.append(self.save_statistics_to_json_action)

        self.enable_visualizations_action = QAction("&Enable visualizations", self)
        self.enable_visualizations_action.setStatusTip("Enable visualization widgets.")
        self.enable_visualizations_action.triggered.connect(self.enable_visualizations_task)
        self._all_actions.append(self.enable_visualizations_action)

        self.disable_visualizations_action = QAction("&Disable visualizations", self)
        self.disable_visualizations_action.setStatusTip("Disable visualization widgets.")
        self.disable_visualizations_action.triggered.connect(self.disable_visualizations_task)
        self._all_actions.append(self.disable_visualizations_action)
        
        self.enable_accessible_color_palette_action = QAction("&Enable accessible palette", self)
        self.enable_accessible_color_palette_action.setStatusTip("Change the color palette to accessible.")
        self.enable_accessible_color_palette_action.triggered.connect(self.enable_accessible_color_palette_task)
        self._all_actions.append(self.enable_accessible_color_palette_action)
        
        self.disable_accessible_color_palette_action = QAction("&Disable accessible palette", self)
        self.disable_accessible_color_palette_action.setStatusTip("Change the color palette to rgb.")
        self.disable_accessible_color_palette_action.triggered.connect(self.disable_accessible_color_palette_task)
        self._all_actions.append(self.disable_accessible_color_palette_action)

        # set up the menu bar
        self.menubar = self.menuBar()
        self.menubar.setFont(MENU_FONT)

        self.document_base_menu = self.menubar.addMenu("&Document Base")
        self.document_base_menu.setFont(MENU_FONT)
        self.document_base_menu.addAction(self.show_document_base_creator_widget_action)
        self.document_base_menu.addSeparator()
        self.document_base_menu.addAction(self.load_document_base_from_bson_action)
        self.document_base_menu.addAction(self.save_document_base_to_bson_action)

        self.table_menu = self.menubar.addMenu("&Table")
        self.table_menu.setFont(MENU_FONT)
        self.table_menu.addAction(self.add_attribute_action)
        self.table_menu.addAction(self.remove_attribute_action)
        self.table_menu.addSeparator()
        self.table_menu.addAction(self.save_table_to_csv_action)

        self.population_menu = self.menubar.addMenu("&Population")
        self.population_menu.setFont(MENU_FONT)
        self.population_menu.addAction(self.interactive_table_population_action)
        self.population_menu.addSeparator()
        self.population_menu.addAction(self.forget_matches_for_attribute_action)
        self.population_menu.addAction(self.forget_matches_action)

        self.settings_menu = self.menubar.addMenu("&Settings")
        self.settings_menu.setFont(MENU_FONT)

        self.statistics_menu = self.settings_menu.addMenu("&Statistics")
        self.statistics_menu.setFont(MENU_FONT)
        self.statistics_menu.addAction(self.enable_collect_statistics_action)
        self.statistics_menu.addAction(self.disable_collect_statistics_action)
        self.statistics_menu.addSeparator()
        self.statistics_menu.addAction(self.save_statistics_to_json_action)

        self.visualizations_menu = self.settings_menu.addMenu("&Visualizations")
        self.visualizations_menu.setFont(MENU_FONT)
        self.visualizations_menu.addAction(self.enable_visualizations_action)
        self.visualizations_menu.addAction(self.disable_visualizations_action)
        self.visualizations_menu.addAction(self.enable_accessible_color_palette_action)
        self.visualizations_menu.addAction(self.disable_accessible_color_palette_action)

        # main UI
        self.central_widget = QWidget(self)
        self.central_widget_layout = QHBoxLayout(self.central_widget)
        self.central_widget_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(self.central_widget)

        self.start_menu_widget = StartMenuWidget(self)
        self.document_base_creator_widget = DocumentBaseCreatorWidget(self)
        self.document_base_creation_widget = DocumentBaseCreatingWidget(self)
        self.document_base_viewer_widget = DocumentBaseViewerWidget(self)
        self.interactive_matching_widget = InteractiveMatchingWidget(self)

        self.to_start_state()

        self.resize(1400, 800)
        self.show()

        logger.info("Initialized MainWindow.")

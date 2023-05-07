import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget, QTableWidget, \
    QTableWidgetItem, QAbstractItemView

from wannadb_parsql.parsql import Parser
from wannadb_parsql.rewrite import update_query_attribute_list, rewrite_query
from wannadb_ui.common import BUTTON_FONT, CODE_FONT, CODE_FONT_BOLD, LABEL_FONT, MainWindowContent, \
    MainWindowContentSection, CustomScrollableListItem, CustomScrollableList, RED, CODE_FONT_SMALLER, \
    INPUT_DOCS_COLUMN_NAME

logger = logging.getLogger(__name__)


class DocumentBaseViewerWidget(MainWindowContent):
    def __init__(self, main_window):
        super(DocumentBaseViewerWidget, self).__init__(main_window, "Document Base Viewer")

        self.everything_populated = False

        # Stats
        self.num_documents_nuggets = QLabel("0 documents | 0 nuggets")
        self.num_documents_nuggets.setFont(LABEL_FONT)
        self.controls_widget_layout.addWidget(self.num_documents_nuggets)

        self.export_table_button = QPushButton("Export Structured Data to CSV")
        self.export_table_button.setFont(BUTTON_FONT)
        self.export_table_button.setIcon(QIcon("wannadb_ui/resources/table.svg"))
        self.export_table_button.clicked.connect(self.main_window.save_table_to_csv_task)
        self.controls_widget_layout.addWidget(self.export_table_button)

        # query
        self.query = MainWindowContentSection(self, "Query")
        self.layout.addWidget(self.query)

        self.query_input_box = QWidget()
        self.query_input_box_layout = QHBoxLayout(self.query_input_box)
        self.query_input_box_layout.setContentsMargins(0, 0, 0, 0)

        self.query_box = QLineEdit()
        self.query_box.setPlaceholderText("Enter a SQL query or manually specify the target attributes below")
        self.query_box.setFont(CODE_FONT)
        self.query_box.setStyleSheet("border: none")
        self.query_input_box_layout.addWidget(self.query_box, stretch=1)

        self.enter_query_button = QPushButton("Run Query")
        self.enter_query_button.setFont(BUTTON_FONT)
        self.enter_query_button.setIcon(QIcon("wannadb_ui/resources/text_cursor.svg"))
        self.enter_query_button.setAutoDefault(True)
        self.enter_query_button.clicked.connect(self._parse_query)
        self.query_input_box_layout.addWidget(self.enter_query_button, alignment=Qt.AlignmentFlag.AlignRight)

        self.query.layout.addWidget(self.query_input_box)

        # attributes
        self.attributes = MainWindowContentSection(self, "Attributes")
        self.layout.addWidget(self.attributes)

        self.attributes_controls = QWidget()
        self.attributes_controls_layout = QHBoxLayout(self.attributes_controls)
        self.attributes_controls_layout.setContentsMargins(0, 0, 0, 0)

        self.add_attribute_button = QPushButton("Add Attribute")
        self.add_attribute_button.setFont(BUTTON_FONT)
        self.add_attribute_button.setIcon(QIcon("wannadb_ui/resources/plus.svg"))
        self.add_attribute_button.clicked.connect(self.main_window.add_attribute_task)
        self.attributes_controls_layout.addWidget(self.add_attribute_button, stretch=1)

        self.populate_remaining_attributes_button = QPushButton("Populate Remaining Attributes")
        self.populate_remaining_attributes_button.setFont(BUTTON_FONT)
        self.populate_remaining_attributes_button.setIcon(QIcon("wannadb_ui/resources/run_run.svg"))
        self.populate_remaining_attributes_button.clicked.connect(self.main_window.interactive_table_population_task)
        self.attributes_controls_layout.addWidget(self.populate_remaining_attributes_button, stretch=1)

        self.attributes_list = CustomScrollableList(self, AttributeWidget, self.attributes_controls)
        self.attributes.layout.addWidget(self.attributes_list)

        # result visualization
        self.results = MainWindowContentSection(self, "Results")
        self.layout.addWidget(self.results)
        self.results_table = QTableWidget()
        self.results_table.setFont(CODE_FONT_SMALLER)
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results.layout.addWidget(self.results_table)

    def update_document_base(self, document_base):
        def _attr_populated(a: str):
            return all(a in d.attribute_mappings.keys() for d in document_base.documents)

        # update documents & nuggets counts
        self.num_documents_nuggets.setText(f"{len(document_base.documents)} documents | {len(document_base.nuggets)} nuggets")

        # update attributes
        self.attributes_list.update_item_list(document_base.attributes, document_base)

        # Everything already populated?
        # Will be used to enable or disable populate and export buttons depending on the completeness of matching
        self.everything_populated = all(_attr_populated(a.name) for a in document_base.attributes)

        # update query
        attributes = [str(a).replace("'", "") for a in document_base.attributes]
        # Take existing query and add manually added attributes if needed
        original_query = self.query_box.text()
        if original_query == "":
            original_query = "SELECT *"
        columns, original_query_parsed = Parser().parse(original_query)
        query = update_query_attribute_list(original_query_parsed, attributes)

        if len(attributes) > 0:
            self.query_box.setText(query)
        else:
            self.query_box.setText("")

        # update cache db
        if self.main_window.cache_db is not None:
            attribute_names = [INPUT_DOCS_COLUMN_NAME]
            attribute_names.extend(attributes)
            query = update_query_attribute_list(original_query_parsed, attribute_names)
            columns, parsed = Parser().parse(query)

            def _get_values_for_column(column):
                for i, document in enumerate(document_base.documents):
                    value = ""
                    if column.name in document.attribute_mappings.keys() and len(
                            document.attribute_mappings[column.name]) > 0:
                        value = document.attribute_mappings[column.name][0].text
                    if value == "":
                        continue
                    yield i, value

            for column in columns:
                if column.name != INPUT_DOCS_COLUMN_NAME and self.main_window.cache_db.table_empty(column.name):
                    logger.info(f"Populating cache table for attribute '{column.name}'")
                    self.main_window.cache_db.store_many(column, _get_values_for_column(column))

            logger.info(f"Columns: {columns}")

            _, rewritten_query = rewrite_query(columns, original_query_parsed)
            logger.info(f"Executing query: '{rewritten_query}'")
            results = self.main_window.cache_db.execute_queries(rewritten_query)[0]

            # update results
            self.results_table.setRowCount(len(results))
            attribute_count = len(attribute_names)
            self.results_table.setColumnCount(attribute_count)
            self.results_table.setHorizontalHeaderLabels(attribute_names)

            for index, row in results.iterrows():
                for c, attribute_name in enumerate(attribute_names):
                    a = row[attribute_name]
                    if a is not None:
                        self.results_table.setItem(index, c, QTableWidgetItem(str(a)))
                    else:
                        self.results_table.setItem(index, c, QTableWidgetItem(""))

            self.results_table.resizeColumnsToContents()

    def enable_input(self):
        self.enter_query_button.setEnabled(True)
        # Enable buttons only conditionally (if needed/possible)
        self.populate_remaining_attributes_button.setEnabled(not self.everything_populated)
        self.export_table_button.setEnabled(self.everything_populated)
        # TODO Apply this to menu entries, too
        self.add_attribute_button.setEnabled(True)
        self.attributes_list.enable_input()

    def disable_input(self):
        self.enter_query_button.setDisabled(True)
        self.populate_remaining_attributes_button.setDisabled(True)
        self.export_table_button.setDisabled(True)
        self.add_attribute_button.setDisabled(True)
        self.attributes_list.disable_input()

    def _parse_query(self):
        if self.main_window.document_base is not None:
            query = self.query_box.text()
            try:
                attributes, parsed = Parser().parse(query)

                attribute_names = [str(attribute) for attribute in attributes]
                logger.info(f"Derived attribute names: {attribute_names}")

                self.main_window.to_busy_state()
                # noinspection PyUnresolvedReferences
                self.main_window.add_attributes.emit(attribute_names, self.main_window.document_base)
            except Exception as e:
                logger.error(str(e))
                self.main_window.status_widget_message.setText(str(e))
                self.main_window.status_widget_progress.setRange(0, 100)
                self.main_window.status_widget_progress.setValue(0)


class AttributeWidget(CustomScrollableListItem):
    def __init__(self, document_base_viewer):
        super(AttributeWidget, self).__init__(document_base_viewer)
        self.document_base_viewer = document_base_viewer
        self.attribute = None

        self.setFixedHeight(40)
        self.setObjectName("attributeWidget")
        self.setStyleSheet("QWidget#attributeWidget { background-color: white}")

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(20, 0, 20, 0)
        self.layout.setSpacing(40)

        self.attribute_name = QLabel()
        self.attribute_name.setFont(CODE_FONT_BOLD)
        self.layout.addWidget(self.attribute_name, alignment=Qt.AlignmentFlag.AlignLeft)

        self.num_matched = QLabel("matches: -")
        self.num_matched.setFont(CODE_FONT)
        self.layout.addWidget(self.num_matched, alignment=Qt.AlignmentFlag.AlignLeft)

        self.buttons_widget = QWidget()
        self.buttons_layout = QHBoxLayout(self.buttons_widget)
        self.buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.buttons_layout.setSpacing(10)
        self.layout.addWidget(self.buttons_widget, alignment=Qt.AlignmentFlag.AlignRight)

        self.start_matching_button = QPushButton()
        self.start_matching_button.setIcon(QIcon("wannadb_ui/resources/run.svg"))
        self.start_matching_button.setToolTip("Populate the cells of this attribute..")
        self.start_matching_button.clicked.connect(self._start_matching_button_clicked)
        self.start_matching_button.hide()
        self.buttons_layout.addWidget(self.start_matching_button)

        self.forget_matches_button = QPushButton()
        self.forget_matches_button.setIcon(QIcon("wannadb_ui/resources/redo.svg"))
        self.forget_matches_button.setToolTip("Clear the cells of this attribute.")
        self.forget_matches_button.clicked.connect(self._forget_matches_button_clicked)
        self.buttons_layout.addWidget(self.forget_matches_button)

        self.remove_button = QPushButton()
        self.remove_button.setIcon(QIcon("wannadb_ui/resources/trash.svg"))
        self.remove_button.setToolTip("Remove this attribute.")
        self.remove_button.clicked.connect(self._remove_button_clicked)
        self.buttons_layout.addWidget(self.remove_button)

    def update_item(self, item, params=None):
        self.attribute = item

        if len(params.attributes) == 0:
            max_attribute_name_len = 10
        else:
            max_attribute_name_len = max(len(attribute.name) for attribute in params.attributes)
        self.attribute_name.setText(self.attribute.name + (" " * (max_attribute_name_len - len(self.attribute.name))))

        mappings_in_some_documents = False
        no_mappings_in_some_documents = False
        num_matches = 0
        for document in params.documents:
            if self.attribute.name in document.attribute_mappings.keys():
                mappings_in_some_documents = True
                if document.attribute_mappings[self.attribute.name] != []:
                    num_matches += 1
            else:
                no_mappings_in_some_documents = True

        if not mappings_in_some_documents and no_mappings_in_some_documents:
            self.num_matched.setStyleSheet(f"color: {RED}")
            self.num_matched.setText("not yet populated")
            self.forget_matches_button.hide()
            self.start_matching_button.show()
        elif mappings_in_some_documents and no_mappings_in_some_documents:
            self.num_matched.setText("only partly populated!")
            self.num_matched.setStyleSheet(f"color: {RED}")
            self.start_matching_button.hide()
            self.forget_matches_button.show()
        else:
            self.num_matched.setText(f"{num_matches} populated cells")
            self.num_matched.setStyleSheet(f"color: black")
            self.start_matching_button.hide()
            self.forget_matches_button.show()

    def enable_input(self):
        self.forget_matches_button.setEnabled(True)
        self.remove_button.setEnabled(True)
        self.start_matching_button.setEnabled(True)

    def disable_input(self):
        self.forget_matches_button.setDisabled(True)
        self.remove_button.setDisabled(True)
        self.start_matching_button.setDisabled(True)

    def _forget_matches_button_clicked(self):
        self.document_base_viewer.main_window.forget_matches_for_attribute_with_given_name_task(self.attribute.name)

    def _start_matching_button_clicked(self):
        self.document_base_viewer.main_window.match_attribute_task(self.attribute.name)

    def _remove_button_clicked(self):
        self.document_base_viewer.main_window.remove_attribute_with_given_name_task(self.attribute.name)


class DocumentBaseCreatorWidget(MainWindowContent):
    def __init__(self, main_window) -> None:
        super(DocumentBaseCreatorWidget, self).__init__(main_window, "Create Document Base")

        self.documents = MainWindowContentSection(self, "Documents:")
        self.layout.addWidget(self.documents)

        self.documents_explanation = QLabel(
            "Enter the path of the directory that contains the documents as .txt files."
        )
        self.documents_explanation.setFont(LABEL_FONT)
        self.documents.layout.addWidget(self.documents_explanation)

        self.path_widget = QFrame()
        self.path_layout = QHBoxLayout(self.path_widget)
        self.path_layout.setContentsMargins(20, 0, 20, 0)
        self.path_layout.setSpacing(10)
        self.path_widget.setObjectName("pathWidget")
        self.path_widget.setStyleSheet("QFrame#pathWidget { background-color: white }")
        self.path_widget.setFixedHeight(40)
        self.documents.layout.addWidget(self.path_widget)

        self.path = QLineEdit()
        self.path.setFont(CODE_FONT_BOLD)
        self.path.setStyleSheet("border: none")
        self.path_layout.addWidget(self.path)

        self.edit_path_button = QPushButton()
        self.edit_path_button.setIcon(QIcon("wannadb_ui/resources/folder.svg"))
        self.edit_path_button.clicked.connect(self._edit_path_button_clicked)
        self.path_layout.addWidget(self.edit_path_button)

        self.attributes = MainWindowContentSection(self, "Attributes:")
        self.layout.addWidget(self.attributes)

        self.labels_explanation = QLabel("Enter the attribute names.")
        self.labels_explanation.setFont(LABEL_FONT)
        self.attributes.layout.addWidget(self.labels_explanation)

        self.create_attribute_button = QPushButton("New Attribute")
        self.create_attribute_button.setFont(BUTTON_FONT)
        self.create_attribute_button.clicked.connect(self._create_attribute_button_clicked)

        self.attribute_names = []
        self.attributes_list = CustomScrollableList(self, AttributeCreatorWidget, self.create_attribute_button)
        self.attributes.layout.addWidget(self.attributes_list)

        self.buttons_widget = QWidget()
        self.buttons_layout = QHBoxLayout(self.buttons_widget)
        self.buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.buttons_layout.setSpacing(10)
        self.buttons_layout.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.attributes.layout.addWidget(self.buttons_widget)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setFont(BUTTON_FONT)
        self.cancel_button.clicked.connect(self._cancel_button_clicked)
        self.buttons_layout.addWidget(self.cancel_button)

        self.create_document_base_button = QPushButton("Create Document Base")
        self.create_document_base_button.setFont(BUTTON_FONT)
        self.create_document_base_button.clicked.connect(self._create_document_base_button_clicked)
        self.buttons_layout.addWidget(self.create_document_base_button)

    def enable_input(self):
        self.edit_path_button.setEnabled(True)
        self.create_attribute_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.create_document_base_button.setEnabled(True)
        self.attributes_list.enable_input()

    def disable_input(self):
        self.edit_path_button.setDisabled(True)
        self.create_attribute_button.setDisabled(True)
        self.cancel_button.setDisabled(True)
        self.create_document_base_button.setDisabled(True)
        self.attributes_list.disable_input()

    def initialize_for_new_document_base(self):
        self.path.setText("")
        self.path.setFocus()
        self.attribute_names = []
        self.attributes_list.update_item_list([])

    def delete_attribute(self, attribute_name):
        self.attribute_names = []
        for attribute_widget in self.attributes_list.item_widgets[:self.attributes_list.num_visible_item_widgets]:
            self.attribute_names.append(attribute_widget.name.text())
        self.attribute_names.remove(attribute_name)
        self.attributes_list.update_item_list(self.attribute_names)
        self.attributes_list.last_item_widget().name.setFocus()

    def _edit_path_button_clicked(self):
        path = str(QFileDialog.getExistingDirectory(self, "Choose a directory of text files."))
        if path != "":
            path = f"{path}/*.txt"
            self.path.setText(path)

    def _create_attribute_button_clicked(self):
        self.attribute_names = []
        for attribute_widget in self.attributes_list.item_widgets[:self.attributes_list.num_visible_item_widgets]:
            self.attribute_names.append(attribute_widget.name.text())
        self.attribute_names.append("")
        self.attributes_list.update_item_list(self.attribute_names)
        self.attributes_list.last_item_widget().name.setFocus()

    def _cancel_button_clicked(self):
        self.main_window.to_start_state()

    def _create_document_base_button_clicked(self):
        self.attribute_names = []
        for attribute_widget in self.attributes_list.item_widgets[:self.attributes_list.num_visible_item_widgets]:
            self.attribute_names.append(attribute_widget.name.text())
        self.main_window.create_document_base_task(self.path.text(), self.attribute_names)


class AttributeCreatorWidget(CustomScrollableListItem):
    def __init__(self, document_base_creator_widget) -> None:
        super(AttributeCreatorWidget, self).__init__(document_base_creator_widget)
        self.document_base_creator_widget = document_base_creator_widget

        self.setFixedHeight(40)
        self.setObjectName("attributeCreatorWidget")
        self.setStyleSheet("QWidget#attributeCreatorWidget { background-color: white}")

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(20, 0, 20, 0)
        self.layout.setSpacing(10)

        self.name = QLineEdit()
        self.name.setFont(CODE_FONT_BOLD)
        self.name.setStyleSheet("border: none")
        self.layout.addWidget(self.name)

        self.delete_button = QPushButton()
        self.delete_button.setIcon(QIcon("wannadb_ui/resources/trash.svg"))
        self.delete_button.clicked.connect(self._delete_button_clicked)
        self.layout.addWidget(self.delete_button)

    def update_item(self, item, params=None):
        self.name.setText(item)

    def _delete_button_clicked(self):
        self.document_base_creator_widget.delete_attribute(self.name.text())

    def enable_input(self):
        self.delete_button.setEnabled(True)

    def disable_input(self):
        self.delete_button.setEnabled(False)


class DocumentBaseCreatingWidget(MainWindowContent):
    def __init__(self, main_window) -> None:
        super(DocumentBaseCreatingWidget, self).__init__(main_window, "Creating the Document Base")

        self.steps = MainWindowContentSection(self, "Please wait while WannaDB prepares the document base.")
        self.layout.addWidget(self.steps)

    def enable_input(self):
        pass

    def disable_input(self):
        pass

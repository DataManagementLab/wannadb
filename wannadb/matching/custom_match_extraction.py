"""
    File containing all code related to extraction of additional nuggets from documents based on custom matches
    annotated by the user.
"""

import abc
import logging
import re
from typing import Any, Tuple, List
from wannadb.data.data import InformationNugget, Attribute, Document

logger: logging.Logger = logging.getLogger(__name__)


class BaseCustomMatchExtractor(abc.ABC):
    """
        Base class for all custom match extractors.
    """

    identifier: str = "BaseCustomMatchExtractor"

    @abc.abstractmethod
    def __call__(self, nugget: InformationNugget, documents: List[Document]) -> List[Tuple[Document, int, int]]:
        """
            Extract additional nuggets from a set of documents based on a custom span of the document.

            :param nugget: The InformationNugget that should be matched against
            :param documents: The set of documents to extract matches from
            :return: Returns a List of Tuples of matching nuggets, where the first entry denotes the corresponding
            document of the nugget, the second and third entry denote the start and end indices of the match.
        """
        raise NotImplementedError


class ExactCustomMatchExtractor(BaseCustomMatchExtractor):
    """
        Extractor based on finding exact matches of the currently annotated custom span.
    """

    identifier: str = "ExactCustomMatchExtractor"

    def __call__(self, nugget: InformationNugget, documents: List[Document]) -> List[Tuple[Document, int, int]]:
        """
            Extracts nuggets from the documents that exactly match the text of the provided nugget.

            :param nugget: The InformationNugget that should be matched against
            :param documents: The set of documents to extract matches from
            :return: Returns a List of Tuples of matching nuggets, where the first entry denotes the corresponding
            document of the nugget, the second and third entry denote the start and end indices of the match.
        """
        new_nuggets = []
        for document in documents:
            doc_text = document.text.lower()
            nug_text = nugget.text.lower()
            start = 0
            while True:
                start = doc_text.find(nug_text, start)
                if start == -1:
                    break
                else:
                    new_nuggets.append((document, start, start + len(nug_text)))
                    start += len(nug_text)

        return new_nuggets


class RegexCustomMatchExtractor(BaseCustomMatchExtractor):
    """
        Extractor based on finding matches in documents based on regular expressions.
    """

    identifier: str = "RegexCustomMatchExtractor"

    def __init__(self) -> None:
        """
            Initializes and pre-compiles the pattern for the regex that is to be scanned due to computational efficiency
        """

        # Create regex pattern to find either the word president or dates.
        # Compile it to one object and re-use it for computational efficiency
        self.regex = re.compile(r'(president)|(\b(?:0?[1-9]|[12][0-9]|3[01])[/\.](?:0?[1-9]|1[0-2])[/\.]\d{4}\b)')

    def __call__(self, nugget: InformationNugget, documents: List[Document]) -> List[Tuple[Document, int, int]]:
        """
            Extracts additional nuggets from all documents based on a regular expression.

            :param nugget: The InformationNugget that should be matched against
            :param documents: The set of documents to extract matches from
            :return: Returns a List of Tuples of matching nuggets, where the first entry denotes the corresponding
            document of the nugget, the second and third entry denote the start and end indices of the match.
        """

        # Return list
        new_nuggets = []

        # Find all matches in all documents to the compiled pattern and append the corresponding document coupled with
        # the start and end indices of the span
        for document in documents:
            for match in self.regex.finditer(document.text.lower()):
                new_nuggets.append((document, match.start(), match.end()))

        # Return results
        return new_nuggets



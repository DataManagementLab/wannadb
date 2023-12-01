"""
    File containing all code related to extraction of additional nuggets from documents based on custom matches
    annotated by the user.
"""

import abc
import logging
import re
import numpy as np
from nltk import ngrams
from typing import Any, Tuple, List
from wannadb import resources
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


class NgramCustomMatchExtractor(BaseCustomMatchExtractor):
    """
        Extractor based on computing ngrams based on the length of the provided nugget, computing embedding vectors
        and deciding on matches based on a threshold-based criterion on their cosine similarity.
    """

    identifier: str = "NgramCustomMatchExtractor"

    def __init__(self, threshold=0.75) -> None:
        """
            Initialize the extractor by setting up necessary resources, and set the threshold for cosine similarity
        """

        self.embedding_model = resources.MANAGER["SBERTBertLargeNliMeanTokensResource"]
        self.cosine_similarity = lambda x, y: np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y))
        self.threshold = threshold

    def __call__(self, nugget: InformationNugget, documents: List[Document]) -> List[Tuple[Document, int, int]]:
        """
            Extracts additional nuggets from all documents by computing ngrams matching the extracted nugget
            structure, computing their cosine similarity to the custom match and thresholding it.

            :param nugget: The InformationNugget that should be matched against
            :param documents: The set of documents to extract matches from
            :return: Returns a List of Tuples of matching nuggets, where the first entry denotes the corresponding
            document of the nugget, the second and third entry denote the start and end indices of the match.
        """

        # List of new matches
        new_matches = []

        # Compute embedding vector for the custom matched nugget
        custom_match_embed = self.embedding_model.encode(nugget.text, show_progress_bar=False)
        ngram_length = len(nugget.text.split(" "))

        for document in documents:
            # Get document text
            doc_text = document.text

            # Create ngrams of the document text according to the length of the custom match
            ngrams_doc = ngrams(doc_text.split(), ngram_length)

            # Create datastructure of ngram texts
            ngrams_data = [" ".join(ng) for ng in ngrams_doc]

            # Get embeddings of each ngram with desired embedding model, one could also combine signals here
            embeddings = self.embedding_model.encode(ngrams_data, show_progress_bar=False)

            # Compute cosine similarity between both embeddings for all ngrams, calculate the distance and add
            # new match if threshold is succeeded. Use loc to find the position in the document
            loc = 0
            for txt, embed_vector in zip(ngrams_data, embeddings):
                cos_sim = self.cosine_similarity(embed_vector, custom_match_embed)
                if cos_sim >= self.threshold:
                    idx = doc_text.find(txt, loc)
                    if idx > -1:
                        new_matches.append((document, idx, idx + len(txt)))
                        loc = idx

        for match in new_matches:
            logger.info(match[1])
            logger.info(match[0].text[match[1]:match[2]])

        # Return new matches
        return new_matches



"""
    File containing all code related to extraction of additional nuggets from documents based on custom matches
    annotated by the user.
"""

import abc
import logging
import multiprocessing
import re
import numpy as np
from itertools import repeat
from nltk import ngrams
from typing import List, Tuple, Union
from transformers import pipeline
from wannadb import resources
from wannadb.data.data import InformationNugget, Document

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

    def __str__(self):
        """
            Represents this class as a string.
        """
        return self.identifier


class ParallelWrapper:
    """
        A wrapper for CustomMatchExtractors to be run in parallel, with data-level parallelism, meaning that
        the similarity search is run in parallel for individual iterations.
    """

    def __init__(self, model: BaseCustomMatchExtractor, threads: int = 4):
        """
            Initialize the wrapper by providing the model that should be parallelized, and the number of threads
            that should be used.

            :param model: The model that should be run in parallel (the __call__ method of it)
            :param threads: The number of threads to use, defaults to 4
        """
        self.model = model
        self.threads = threads

    def __call__(self, nugget: InformationNugget, documents: List[Document]) -> List[Tuple[Document, int, int]]:
        """
            Extract nuggets similar to the provided nugget from the given list of documents, by running the extraction
            in parallel document-wise, and concatenate the results of individual threads into one result.

            :param nugget: The InformationNugget that should be matched against
            :param documents: The set of documents to extract matches from
            :return: Returns a List of Tuples of matching nuggets, where the first entry denotes the corresponding
            document of the nugget, the second and third entry denote the start and end indices of the match.
        """

        # The thread of pools
        pool = multiprocessing.Pool(self.threads)

        # TODO: Maybe apply_async?
        # Call the individual iterations of the model and distribute the document iterations among them
        thread_results = pool.starmap(self.model.__call__, zip(repeat(nugget), documents))

        # Close and terminate the pool of threads
        pool.close()
        pool.terminate()

        # Post-process results by collapsing into one list and return
        logger.info([result[0] for result in thread_results if len(result) > 0])
        return [result[0] for result in thread_results if len(result) > 0]

    def __str__(self):
        """
            Represents this class as a string.
        """
        return self.model.identifier + f"in parallel with {self.threads} threads"


class ExactCustomMatchExtractor(BaseCustomMatchExtractor):
    """
        Extractor based on finding exact matches of the currently annotated custom span.
    """

    identifier: str = "ExactCustomMatchExtractor"

    def __call__(
            self, nugget: InformationNugget, documents: Union[Document, List[Document]]
    ) -> List[Tuple[Document, int, int]]:
        """
            Extracts nuggets from the documents that exactly match the text of the provided nugget.

            :param nugget: The InformationNugget that should be matched against
            :param documents: The set of documents to extract matches from, or a single document
            :return: Returns a List of Tuples of matching nuggets, where the first entry denotes the corresponding
            document of the nugget, the second and third entry denote the start and end indices of the match.
        """
        new_nuggets = []

        # If only one document is provided, e.g. by loop level parallelization
        if not isinstance(documents, list):
            documents = [documents]

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

    def __call__(
            self, nugget: InformationNugget, documents: Union[Document, List[Document]]
    ) -> List[Tuple[Document, int, int]]:
        """
            Extracts additional nuggets from all documents based on a regular expression.

            :param nugget: The InformationNugget that should be matched against
            :param documents: The set of documents to extract matches from, or a single document
            :return: Returns a List of Tuples of matching nuggets, where the first entry denotes the corresponding
            document of the nugget, the second and third entry denote the start and end indices of the match.
        """

        # Return list
        new_nuggets = []

        # If only one document is provided, e.g. by loop level parallelization
        if not isinstance(documents, list):
            documents = [documents]

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

    def __call__(
            self, nugget: InformationNugget, documents: Union[Document, List[Document]]
    ) -> List[Tuple[Document, int, int]]:
        """
            Extracts additional nuggets from all documents by computing ngrams matching the extracted nugget
            structure, computing their cosine similarity to the custom match and thresholding it.

            :param nugget: The InformationNugget that should be matched against
            :param documents: The set of documents to extract matches from, or a single document
            :return: Returns a List of Tuples of matching nuggets, where the first entry denotes the corresponding
            document of the nugget, the second and third entry denote the start and end indices of the match.
        """

        # List of new matches
        new_matches = []

        # Compute embedding vector for the custom matched nugget
        custom_match_embed = self.embedding_model.encode(nugget.text, show_progress_bar=False)
        ngram_length = len(nugget.text.split(" "))

        # If only one document is provided, e.g. by loop level parallelization
        if not isinstance(documents, list):
            documents = [documents]

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

        # Return new matches
        return new_matches


class QuestionAnsweringCustomMatchExtractor(BaseCustomMatchExtractor):
    """
        Extractor based on prompting a pretrained question answering LLM and extracting a start and end span, by asking
        to extract a similar phrase to an input phrase.
    """

    identifier: str = "QuestionAnsweringCustomMatchExtractor"

    def __init__(self, threshold=0.1) -> None:
        """
            Initialize the question answering extractor by initializing the necessary pre-processing and model pipeline
            from the HuggingFace hub, and setting a threshold for filtering out bad guesses

            :param threshold: The threshold the score needs to exceed to be classified as good guess.
        """

        # Create pipeline of question answering using the respective model and tokenizer
        self.qa_pipeline = pipeline(
            'question-answering',
            model="deepset/roberta-base-squad2",
            tokenizer="deepset/roberta-base-squad2"
        )

        # Set threshold for the score by which a match is classified as valid
        self.threshold = threshold

    def __call__(
            self, nugget: InformationNugget, documents: Union[Document, List[Document]]
    ) -> List[Tuple[Document, int, int]]:
        """
            Extracts additional nuggets from all documents by prompting the QA LLM for similar words to the provided
            information nugget, e.g.

                > What word is most similar to <nugget>?
                > What is the <attribute>, given the example <nugget>?

            :param nugget: The InformationNugget that should be matched against
            :param documents: The set of documents to extract matches from, or a single document
            :return: Returns a List of Tuples of matching nuggets, where the first entry denotes the corresponding
            document of the nugget, the second and third entry denote the start and end indices of the match.
        """

        # List of new matches
        new_matches = []

        # If only one document is provided, e.g. by loop level parallelization
        if not isinstance(documents, list):
            documents = [documents]

        for document in documents:

            # Create input for QA model
            model_input = {
                'question': f'What word in this text is most similar to {nugget.text}?',
                'context': document.text
            }

            # Compute model output and add to new nuggets if the score is sufficiently high enough
            model_output = self.qa_pipeline(model_input)
            if model_output["score"] > self.threshold:
                new_matches.append((document, model_output["start"], model_output["end"]))
                # logger.info(model_output)

        return new_matches


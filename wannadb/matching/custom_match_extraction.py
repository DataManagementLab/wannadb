"""
    File containing all code related to extraction of additional nuggets from documents based on custom matches
    annotated by the user.
"""

import abc
import faiss
import logging
import multiprocessing
import pandas as pd
import numpy as np
import time
from itertools import repeat
from nltk import ngrams
from nltk.corpus import wordnet
from typing import List, Tuple
from transformers import pipeline
from wannadb import resources
from wannadb.data.data import InformationNugget, Document

logger: logging.Logger = logging.getLogger(__name__)


class BaseCustomMatchExtractor(abc.ABC):
    """
        Base class for all custom match extractors.
    """

    identifier: str = "BaseCustomMatchExtractor"
    time_keeping = pd.DataFrame(
        columns=["document", "remaining_documents", "time", "document_text", "feedback_start", "feedback_end"]
    )

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

    @staticmethod
    def preprocess_documents(documents: List[Document]) -> List[Document]:
        """
            Apply any needed preprocessing to the provided document base.

            :param documents: The documents to preprocess
            :return: A list of documents in the same order, with potential preprocessing
        """

        # If only one document is provided, e.g. by loop level parallelization
        if not isinstance(documents, list):
            documents = [documents]
        return documents

    def perform_time_keeping(
            self, document: Document, remaining_document_count: int, t: float, start: int, end: int
    ) -> None:
        """
            Perform time-keeping for this extractor by saving the document that has been given feedback to,
            the remaining document count,  the time needed for that round of feedback, and the span of the
            given feedback.

            :param document: The document that is given feedback for
            :param remaining_document_count: How many documents are still left
            :param t: The time needed for that feedback round
            :param start: The index of the beginning of the feedback span
            :param end: The index of the end of the feedback span
            :return: None
        """

        # Append a new row to the dataframe and insert the new entry
        self.time_keeping.loc[
            0 if pd.isnull(self.time_keeping.index.max()) else self.time_keeping.index.max() + 1
        ] = [document.name, remaining_document_count, t, document.text, start, end]

    def reset_time_keeping(self):
        """
            Resets the time keeping dataframe to be empty.
        """

        self.time_keeping = pd.DataFrame(
            columns=["document", "remaining_documents", "time", "document_text", "feedback_start", "feedback_end"]
        )


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


class DummyCustomMatchExtractor(BaseCustomMatchExtractor):
    """
        Extractor that does not do anything.
    """

    identifier: str = "DummyCustomMatchExtractor"

    def __call__(
            self, nugget: InformationNugget, documents: List[Document]
    ) -> List[Tuple[Document, int, int]]:
        """
            Does not extract any nuggets, returns an empty list

            :param nugget: The InformationNugget that should be matched against
            :param documents: The set of documents to extract matches from, or a single document
            :return: Returns an empty list
        """

        return []


class ExactCustomMatchExtractor(BaseCustomMatchExtractor):
    """
        Extractor based on finding exact matches of the currently annotated custom span.
    """

    identifier: str = "ExactCustomMatchExtractor"

    def __call__(
            self, nugget: InformationNugget, documents: List[Document]
    ) -> List[Tuple[Document, int, int]]:
        """
            Extracts nuggets from the documents that exactly match the text of the provided nugget.

            :param nugget: The InformationNugget that should be matched against
            :param documents: The set of documents to extract matches from, or a single document
            :return: Returns a List of Tuples of matching nuggets, where the first entry denotes the corresponding
            document of the nugget, the second and third entry denote the start and end indices of the match.
        """
        new_nuggets = []

        # Potential preprocessing
        documents = self.preprocess_documents(documents)

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
            self, nugget: InformationNugget, documents: List[Document]
    ) -> List[Tuple[Document, int, int]]:
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

        # Potential preprocessing
        documents = self.preprocess_documents(documents)

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
            self, nugget: InformationNugget, documents: List[Document]
    ) -> List[Tuple[Document, int, int]]:
        """
            Extracts additional nuggets from all documents by prompting the QA LLM for similar words to the provided
            information nugget, e.g.

                > What word is most similar to <nugget>?
                > What is the <attribute>, given the example <nugget>?

            :param nugget: The InformationNugget that should be matched against
            :param documents: The set of documents to extract matches from
            :return: Returns a List of Tuples of matching nuggets, where the first entry denotes the corresponding
            document of the nugget, the second and third entry denote the start and end indices of the match.
        """

        # List of new matches
        new_matches = []

        # Potential preprocessing
        documents = self.preprocess_documents(documents)

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

        return new_matches


class WordNetSimilarityCustomMatchExtractor(BaseCustomMatchExtractor):
    """
        Extractor that uses a semantic / lexical network (WordNet) to capture relationships between concepts and
        computing their Wu-Palmer-Similarity as a measure of semantic similarity. The depth of the first common
        preprocessor w.r.t to two concepts is taken as the similarity score.
    """

    identifier: str = "WordNetSimilarityCustomMatchExtractor"

    def __init__(self, threshold=0.6) -> None:
        """
            Initialize this extractor by specifying the threshold that needs to be succeeded in order to classify
            something as a match.

            :param threshold: The threshold that is to be succeeded.
        """

        # Set threshold for the score by which a match is classified as valid
        self.threshold = threshold

    def __call__(
            self, nugget: InformationNugget, documents: List[Document]
    ) -> List[Tuple[Document, int, int]]:
        """
            Extracts tokens similar to the provided nugget from all provided documents by computing their first
            common predecessor, calculating its depth w.r.t to the nuggets, and thresholding it to classify matches.

            :param nugget: The InformationNugget that should be matched against
            :param documents: The set of documents to extract matches from
            :return: Returns a List of Tuples of matching nuggets, where the first entry denotes the corresponding
            document of the nugget, the second and third entry denote the start and end indices of the match.
        """

        # List of new matches
        matches = []

        # Potential preprocessing
        documents = self.preprocess_documents(documents)

        # Compute the wordnet category for the nugget
        nugget_syn = wordnet.synsets(nugget.text)

        # If there is none, terminate since it won't work
        if len(nugget_syn) < 1:
            logger.info(f"Custom match {nugget.text} has no WordNet entry, no Wu-Palmer-Similarity computable")
            return []

        # Potential preprocessing
        documents = self.preprocess_documents(documents)

        # Otherwise, iterate through all documents, all tokens of it and get the wordnet entry
        # Use loc to keep track of current position in a document and to shorten search time in documents
        for doc in documents:
            loc = 0
            for tok in doc.text.split(" "):
                syn = wordnet.synsets(tok)

                # If there is one: Compute Wu-Palmer-Similarity and threshold it to classify matches
                if len(syn) > 0:
                    if nugget_syn[0].wup_similarity(syn[0]) > self.threshold:

                        # Find the index in the text and append
                        idx = doc.text.find(tok, loc)
                        if idx > -1:
                            logger.info(tok)
                            matches.append((doc, idx, idx + len(tok)))
                            loc = idx

        # Return the matches
        return matches


class FaissSemanticSimilarityExtractor(BaseCustomMatchExtractor):
    """
        Extractor that extracts syntactically and semantically similar words from all documents given a query. For this,
        the embeddings of every token is computed once and indexed using faiss, allowing very fast indexing and similarity
        search. If an embedding of a single token is found to be similar to the whole query, it is further examined by
        matching it to the ngram structure of the query. A threshold is used to determine whether a candidate ngram is
        sufficient to classify it as a match.
    """

    identifier: str = "FaissSemanticSimilarityExtractor"

    def __init__(self, document_base, threshold=0.9, top_k=10) -> None:
        """
            Initialize the Faiss extractor by taking the document base and computing the embeddings of each token
            in each document. This is time-consuming, but only needs to be done once. The embeddings are stored w.r.t
            their document of appearance and in accord to their respective names to allow for easier indexing later on.
            Further hyper-parameters, such as the threshold and the top_k are defined.

            :param document_base: The current document base
            :param threshold: The threshold at which to consider a candidate to be a match
            :param top_k: The top k guesses to extract for every query
        """

        # Set threshold for the score by which a match is classified as valid
        self.threshold = threshold
        self.top_k = top_k

        # The distance function, currently: cosine similarity
        self.distance = lambda x, y: np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y))

        # Get the embedding model resource from the resource manager
        self.embedding_model = resources.MANAGER["SBERTBertLargeNliMeanTokensResource"]

        # Get all documents and their respective tokens, preprocess and embed each token of each document
        t1 = time.time()
        self.documents = document_base.documents
        self.document_names = [x.name for x in document_base.documents]
        self.embedded_tokens_per_document = np.array(
            [self.embedding_model.encode(doc.text.split()) for doc in self.documents]
        )

        # Time logging
        logger.info(f"Embedding all tokens of {len(self.documents)} documents took {time.time() - t1} seconds.")

    def __call__(
            self, nugget: InformationNugget, documents: List[Document]
    ) -> List[Tuple[Document, int, int]]:
        """
            Extracts tokens similar to the provided nugget from all provided documents using the FAISS method.

            :param nugget: The InformationNugget that should be matched against
            :param documents: The set of documents to extract matches from
            :return: Returns a List of Tuples of matching nuggets, where the first entry denotes the corresponding
            document of the nugget, the second and third entry denote the start and end indices of the match.
        """

        # List of new matches
        matches = []

        # Potential preprocessing
        documents = self.preprocess_documents(documents)

        # Retrieve the ids of documents that are still remaining
        relevant_document_ids = []
        for remaining_doc in documents:
            try:
                relevant_document_ids.append(self.document_names.index(remaining_doc.name))
            except ValueError:
                logger.warning("Document referenced that cannot be found in document base - should not happen")
        doc_array = np.array(self.documents)[relevant_document_ids]

        # Given the ids, create a flat list of nuggets
        flat_token_list = np.array([
            tok
            for doc_tokens in self.embedded_tokens_per_document[relevant_document_ids]
            for tok in doc_tokens
        ])

        # Create a Faiss index mapping given these tokens
        faiss_index = faiss.IndexIDMap(faiss.IndexFlatIP(flat_token_list[0].shape[-1]))
        faiss_index.add_with_ids(flat_token_list, np.array(range(0, len(flat_token_list))))

        # Encode the query and to semantic similarity search of its embedding to all other indexed embedding vectors
        query_vector = self.embedding_model.encode([nugget.text])
        top_k_indices = faiss_index.search(query_vector, self.top_k)[1][0]

        # Get tuple of potential ngram indices that contain this nugget
        query_nugget_split = nugget.text.split()
        query_nugget_ngram_length = len(query_nugget_split)
        potential_ngram_tuple_idx = [
            (i, i + query_nugget_ngram_length) for i in range(-query_nugget_ngram_length + 1, 1)
        ]

        # Get the embeddings of each 1gram of the potential ngram query nugget. If the query nugget in itself
        # is already an onegram, this corresponds just to query_vector
        query_nugget_embeddings = [
            self.embedding_model.encode([query_nugget_split[i]]) for i in range(0, query_nugget_ngram_length)
        ] if query_nugget_ngram_length > 1 else [query_vector]

        # Compute a mapping that captures the boundaries of the intervals of its tokens
        reverse_mapping = [0]
        for doc in doc_array:
            reverse_mapping.append(len(doc.text.split()) + reverse_mapping[-1])

        # Fetch the matching tokens from the documents given the reverse mapping
        for match_id in top_k_indices:

            # Find the index of the respective document by assigning it into the proper token range
            document_idx = np.argmax(np.array(reverse_mapping) > match_id) - 1
            doc = doc_array[document_idx]
            doc_text_split = doc.text.split()

            # Calculate position of match in document
            pos_in_doc = match_id - reverse_mapping[document_idx]

            # Compute the distances of this 1gram to each 1gram of the ngram query nugget
            distances_to_query_1grams = [
                self.distance(flat_token_list[match_id], qne[0]) for qne in query_nugget_embeddings
            ]

            # If some threshold is exceeded for a ngram match
            if np.max(distances_to_query_1grams) > 0.9:

                # Compute the corresponding index in the document ngram list and extract a span around it w.r.t the
                # structure of the query nugget
                corresponding_onegram_idx = np.argmax(distances_to_query_1grams)
                offset_to_end = query_nugget_ngram_length - corresponding_onegram_idx
                potential_match = " ".join(
                    doc_text_split[pos_in_doc - corresponding_onegram_idx: pos_in_doc + offset_to_end]
                )

                # Find its actual index in the document and append it to the list of matches
                doc_start_idx = doc.text.find(potential_match)
                doc_end_idx = doc_start_idx + len(potential_match)
                matches.append((doc, doc_start_idx, doc_end_idx))

                # Logging
                logger.info("Extractor found match: " + potential_match)

            # TODO: Maybe add the single nugget itself if the ngrams do not match?
            # Eg: Query: "Sri Lanka", found: "Germany" -> the Germany etc. is worse than just Germany
            # Or simply assume that it would've been picked up earlier

            """
            OLD VERSION; MIGHT STILL TRY OUT
            
            # Try to match it to the ngram length of the query
            for (ngram_idx_1, ngram_idx_2) in potential_ngram_tuple_idx:
                potential_ngram = doc_text_split[pos_in_doc + ngram_idx_1: pos_in_doc + ngram_idx_2]

                # If it is within the bounds of the document
                if len(potential_ngram) == query_nugget_ngram_length:
                    potential_match = " ".join(potential_ngram)
                    potential_match_embed = self.embedding_model.encode([potential_match])

                    # If some distance is exceeded, append it to the list of matches
                    if self.distance(query_vector[0], potential_match_embed[0]) > self.threshold:

                        # Get the index of the match in the document
                        doc_start_idx = doc.text.find(potential_match)
                        doc_end_idx = doc_start_idx + len(potential_match)
                        matches.append((doc, doc_start_idx, doc_end_idx))
            """

        return matches

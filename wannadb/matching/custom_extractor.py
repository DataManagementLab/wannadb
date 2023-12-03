import logging
import re
import spacy
from spacy.tokenizer import Tokenizer
from typing import Tuple, List
from wannadb.data.data import InformationNugget, Document
from wannadb.matching.custom_match_extraction import BaseCustomMatchExtractor

logger: logging.Logger = logging.getLogger(__name__)


class CustomSimilaritySpanExtractor(BaseCustomMatchExtractor):
    """
        This extractor aims to identify similar patterns among tokens that share similar semantic meanings.
    """
    identifier: str = "CustomHighlightExtractor"

    def __init__(self) -> None:
        """
            Initiate the spaCy pipeline.
            Incorporate a custom tokenization rule that exclusively extracts tokens separated by whitespaces.
        """
        self.nlp = spacy.load("en_core_web_md")
        self.nlp.tokenizer = Tokenizer(self.nlp.vocab, token_match=re.compile(r'\S+').match)

    def __call__(self, nugget: InformationNugget, documents: List[Document]) -> List[Tuple[Document, int, int]]:
        """

            When the document contains a token with a similar semantic meaning to a token in the custom nugget,
            the extractor captures the corresponding span, maintains the same format as in the nugget,
            and includes this new span as a new nugget.

            :param nugget: The InformationNugget that should be matched against
            :param documents: The set of documents to extract matches from
            :return: Returns a List of Tuples of matching nuggets, where the first entry denotes the corresponding
            document of the nugget, the second and third entry denote the start and end indices of the match.
        """
        nugget_tokens = [token for token in self.nlp(nugget.text) if token.text.strip() != ""]

        logger.info("Test")
        logger.info(nugget_tokens)
        result = []
        for doc in documents:
            document_tokens = [token for token in self.nlp(doc.text)]

            logger.info("new document")
            for i, doc_tok in enumerate(document_tokens):
                for j, nug_tok in enumerate(nugget_tokens):
                    sim = doc_tok.similarity(nug_tok)
                    if sim > 0.95 and not nug_tok.is_stop:
                        start_index_tok = i - j
                        end_index_tok = start_index_tok + len(nugget_tokens) - 1
                        logger.info("high sim: ")
                        logger.info(doc_tok.text)
                        logger.info(nug_tok.text)
                        span = document_tokens[max(start_index_tok, 0):min(end_index_tok + 1, len(document_tokens) - 1)]
                        new_nugget = " ".join([tok.text for tok in span])

                        start_index = doc.text.find(new_nugget)
                        end_index = start_index + len(new_nugget)
                        logger.info("extracted new nugget: " + new_nugget)
                        result.append((doc, start_index, end_index))

        return result

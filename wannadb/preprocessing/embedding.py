import abc
import logging
import time
from bisect import bisect_left, bisect_right
from typing import Any, Dict, List

import numpy as np
import torch

from wannadb import resources
from wannadb.configuration import BasePipelineElement, register_configurable_element
from wannadb.data.data import Attribute, DocumentBase, InformationNugget
from wannadb.data.signals import ContextSentenceEmbeddingSignal, LabelEmbeddingSignal, RelativePositionSignal, \
    TextEmbeddingSignal, UserProvidedExamplesSignal, NaturalLanguageLabelSignal, CachedContextSentenceSignal, \
    SentenceStartCharsSignal, DocumentSentenceEmbeddingSignal
from wannadb.interaction import BaseInteractionCallback
from wannadb.statistics import Statistics
from wannadb.status import BaseStatusCallback

logger: logging.Logger = logging.getLogger(__name__)


class BaseEmbedder(BasePipelineElement, abc.ABC):
    """
    Base class for all embedders.

    Embedders work with nuggets and attributes and transform their signals and other information into embedding signals.
    """
    identifier: str = "BaseEmbedder"

    def _use_status_callback_for_embedder(
            self,
            status_callback: BaseStatusCallback,
            element: str,
            ix: int,
            total: int
    ) -> None:
        """
        Helper method that calls the status callback at regular intervals.

        :param status_callback: status callback to call
        :param element: 'nuggets' or 'attributes'
        :param ix: index of the current element
        :param total: total number of elements
        """
        if total == 0:
            status_callback(f"Embedding {element} with {self.identifier}...", -1)
        elif ix == 0:
            status_callback(f"Embedding {element} with {self.identifier}...", 0)
        else:
            interval: int = total // 10
            if interval != 0 and ix % interval == 0:
                status_callback(f"Embedding {element} with {self.identifier}...", ix / total)

    def _call(
            self,
            document_base: DocumentBase,
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        # compute embeddings for the attributes
        if len(self.generated_signal_identifiers["attributes"]) > 0:
            attributes: List[Attribute] = document_base.attributes
            logger.info(f"Embed {len(attributes)} attributes with {self.identifier}.")
            tick: float = time.time()
            status_callback(f"Embedding attributes with {self.identifier}...", -1)
            statistics["attributes"]["num_attributes"] = len(attributes)
            self._embed_attributes(attributes, interaction_callback, status_callback, statistics["attributes"])
            status_callback(f"Embedding attributes with {self.identifier}...", 1)
            tack: float = time.time()
            logger.info(f"Embedded {len(attributes)} attributes with {self.identifier} in {tack - tick} seconds.")
            statistics["attributes"]["runtime"] = tack - tick

        # compute embeddings for the documents
        if len(self.generated_signal_identifiers["documents"]) > 0:
            logger.info(f"Embed {len(document_base.documents)} documents with {self.identifier}.")
            tick: float = time.time()
            status_callback(f"Embedding documents with {self.identifier}...", -1)
            self._embed_documents(document_base, interaction_callback, status_callback, statistics["documents"])
            status_callback(f"Embedding documents with {self.identifier}...", 1)
            tack: float = time.time()
            logger.info(
                f"Embedded {len(document_base.documents)} documents with {self.identifier} in {tack - tick} seconds.")
            statistics["documents"]["runtime"] = tack - tick

        # compute embeddings for the nuggets
        nuggets: List[InformationNugget] = document_base.nuggets

        if len(self.generated_signal_identifiers["nuggets"]) == 0 or len(nuggets) == 0:
            return

        # Check if there is already an embedding for this signal
        # (assuming that each embedder will always generate exactly one signal)
        if self.generated_signal_identifiers["nuggets"][0] in nuggets[0].signals.keys():
            # Try to determine if the dimensions are correct (should match those of the embedding of the attributes)
            if len(self.generated_signal_identifiers["attributes"]) > 0:
                if len(attributes) > 0 and attributes[0].signals[
                    self.generated_signal_identifiers["attributes"][0]].value.shape == nuggets[0].signals[
                    self.generated_signal_identifiers["attributes"][0]].value.shape:
                    logger.info(
                        f"No need to embedd nuggets again with {self.identifier}, existing embeddings with correct dimensions found.")
                    return
                logger.info(
                    f"Dimension missmatch, recomputing embeddings for {self.generated_signal_identifiers['nuggets'][0]} with {self.identifier}.")
            else:
                # Cannot check dimensions, but assuming they are correct do to lack of other evidence
                logger.info(
                    f"Found existing embeddings for {self.generated_signal_identifiers['nuggets'][0]}, assuming they were created with {self.identifier} (even though dimension check is not possible.")
                return

        # If no existing embeddings are found, or dimensions are not matching continue with embedding
        logger.info(f"Embed {len(nuggets)} nuggets with {self.identifier}.")
        tick: float = time.time()
        status_callback(f"Embedding nuggets with {self.identifier}...", -1)
        statistics["nuggets"]["num_nuggets"] = len(nuggets)
        self._embed_nuggets(nuggets, interaction_callback, status_callback, statistics["nuggets"])
        status_callback(f"Embedding nuggets with {self.identifier}...", 1)
        tack: float = time.time()
        logger.info(f"Embedded {len(nuggets)} nuggets with {self.identifier} in {tack - tick} seconds.")
        statistics["nuggets"]["runtime"] = tack - tick

    def _embed_nuggets(
            self,
            nuggets: List[InformationNugget],
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        """
        Compute embeddings for the given list of nuggets.

        :param nuggets: list of nuggets to work on
        :param interaction_callback: callback to allow for user interaction
        :param status_callback: callback to communicate current status (message and progress)
        :param statistics: statistics object to collect statistics
        """
        pass  # default behavior: do nothing

    def _embed_attributes(
            self,
            attributes: List[Attribute],
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        """
        Compute embeddings for the given list of InformationNuggets.

        :param attributes: list of Attributes to work on
        :param interaction_callback: callback to allow for user interaction
        :param status_callback: callback to communicate current status (message and progress)
        :param statistics: statistics object to collect statistics
        """
        pass  # default behavior: do nothing

    def _embed_documents(
            self,
            doc_base: DocumentBase,
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        """
        Compute embeddings for the given list of InformationNuggets.

        :param doc_base: document base to work on
        :param interaction_callback: callback to allow for user interaction
        :param status_callback: callback to communicate current status (message and progress)
        :param statistics: statistics object to collect statistics
        """
        pass  # default behavior: do nothing


########################################################################################################################
# actual embedders
########################################################################################################################


class BaseSBERTEmbedder(BaseEmbedder, abc.ABC):
    """Base class for all embedders based on SBERT."""
    identifier: str = "BaseSBERTEmbedder"

    def __init__(self, sbert_resource_identifier: str) -> None:
        """
        Initialize the embedder.

        :param sbert_resource_identifier: identifier of the SBERT model resource
        """
        super(BaseSBERTEmbedder, self).__init__()
        self._sbert_resource_identifier: str = sbert_resource_identifier

        logger.debug(f"Initialized '{self.identifier}'.")

    def _encode_unique(self, texts: List[str]) -> List[np.ndarray]:
        if not texts:
            return []
        unique_texts = list(dict.fromkeys(texts))
        resources.MANAGER.load(self._sbert_resource_identifier)
        embeddings = resources.MANAGER[self._sbert_resource_identifier].encode(
            unique_texts, show_progress_bar=False
        )
        by_text = dict(zip(unique_texts, embeddings))
        # Preserve every input/label and give each recipient an independent array.
        return [by_text[text].copy() for text in texts]

    def to_config(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier,
            "sbert_resource_identifier": self._sbert_resource_identifier
        }

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "BaseSBERTEmbedder":
        return cls(config["sbert_resource_identifier"])


@register_configurable_element
class SBERTLabelEmbedder(BaseSBERTEmbedder):
    """Label embedder based on SBERT."""
    identifier: str = "SBERTLabelEmbedder"

    required_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [NaturalLanguageLabelSignal.identifier],
        "attributes": [NaturalLanguageLabelSignal.identifier],
        "documents": []
    }

    generated_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [LabelEmbeddingSignal.identifier],
        "attributes": [LabelEmbeddingSignal.identifier],
        "documents": []
    }

    def _embed_nuggets(
            self,
            nuggets: List[InformationNugget],
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        texts: List[str] = [nugget[NaturalLanguageLabelSignal] for nugget in nuggets]
        embeddings: List[np.ndarray] = self._encode_unique(texts)

        for nugget, embedding in zip(nuggets, embeddings):
            nugget[LabelEmbeddingSignal] = LabelEmbeddingSignal(embedding)

    def _embed_attributes(
            self,
            attributes: List[Attribute],
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        texts: List[str] = [attribute[NaturalLanguageLabelSignal] for attribute in attributes]
        embeddings: List[np.ndarray] = []
        # if there are no texts, embeddings will be an empty list
        # this is necessary as newer versions of SentenceTransformers throw an error if texts is an empty list
        if texts != []:
            embeddings: List[np.ndarray] = self._encode_unique(texts)

        for attribute, embedding in zip(attributes, embeddings):
            attribute[LabelEmbeddingSignal] = LabelEmbeddingSignal(embedding)


@register_configurable_element
class SBERTTextEmbedder(BaseSBERTEmbedder):
    """Text embedder based on SBERT."""
    identifier: str = "SBERTTextEmbedder"

    required_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [],
        "attributes": [],
        "documents": []
    }

    generated_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [TextEmbeddingSignal.identifier],
        "attributes": [],
        "documents": []
    }

    def _embed_nuggets(
            self,
            nuggets: List[InformationNugget],
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        texts: List[str] = [nugget.text for nugget in nuggets]
        embeddings: List[np.ndarray] = self._encode_unique(texts)

        for nugget, embedding in zip(nuggets, embeddings):
            nugget[TextEmbeddingSignal] = TextEmbeddingSignal(embedding)


@register_configurable_element
class SBERTExamplesEmbedder(BaseSBERTEmbedder):
    """SBERT-based embedder to embed user-provided example texts."""
    identifier: str = "SBERTExamplesEmbedder"

    required_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [],
        "attributes": [UserProvidedExamplesSignal.identifier],
        "documents": []
    }

    generated_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [],
        "attributes": [TextEmbeddingSignal.identifier],
        "documents": []
    }

    def _embed_attributes(
            self,
            attributes: List[Attribute],
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        for ix, attribute in enumerate(attributes):
            self._use_status_callback_for_embedder(status_callback, "attributes", ix, len(attributes))
            texts: List[str] = attribute[UserProvidedExamplesSignal]
            if texts != []:
                embeddings: List[np.ndarray] = self._encode_unique(texts)
                embedding: np.ndarray = np.mean(embeddings, axis=0)
                attribute[TextEmbeddingSignal] = TextEmbeddingSignal(embedding)
                statistics["num_has_examples"] += 1
            else:
                statistics["num_no_examples"] += 1


@register_configurable_element
class SBERTContextSentenceEmbedder(BaseSBERTEmbedder):
    """Context sentence embedder based on SBERT."""
    identifier: str = "SBERTContextSentenceEmbedder"

    required_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [CachedContextSentenceSignal.identifier],
        "attributes": [],
        "documents": []
    }

    generated_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [ContextSentenceEmbeddingSignal.identifier],
        "attributes": [],
        "documents": []
    }

    def _embed_nuggets(
            self,
            nuggets: List[InformationNugget],
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        texts: List[str] = [nugget[CachedContextSentenceSignal]["text"] for nugget in nuggets]

        # compute embeddings
        embeddings: List[np.ndarray] = self._encode_unique(texts)

        for nugget, embedding in zip(nuggets, embeddings):
            nugget[ContextSentenceEmbeddingSignal] = ContextSentenceEmbeddingSignal(embedding)


@register_configurable_element
class SBERTDocumentSentenceEmbedder(BaseSBERTEmbedder):
    """Document sentence embedder based on SBERT."""
    identifier: str = "SBERTDocumentSentenceEmbedder"

    required_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [],
        "attributes": [],
        "documents": [SentenceStartCharsSignal.identifier]
    }

    generated_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [],
        "attributes": [],
        "documents": [DocumentSentenceEmbeddingSignal.identifier]
    }

    def _embed_documents(
            self,
            document_base: DocumentBase,
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        count_docs_that_needed_sentence_embeddings = 0
        for doc in document_base.documents:
            # Look for DocumentSentenceEmbeddingSignal
            if not 'DocumentSentenceEmbeddingSignal' in doc.signals:
                logger.debug("Embedding document sentences.")
                sentences: List[str] = doc.sentences
                embeddings: List[np.ndarray] = self._encode_unique(sentences)
                doc[DocumentSentenceEmbeddingSignal] = DocumentSentenceEmbeddingSignal(embeddings)
                count_docs_that_needed_sentence_embeddings += 1


@register_configurable_element
class BERTContextSentenceEmbedder(BaseEmbedder):
    """
    Context sentence embedder based on BERT.

    Computes the context embedding of an InformationNugget as the mean of the final hidden states of the tokens that make up
    the nugget in its context sentence.
    """
    identifier: str = "BERTContextSentenceEmbedder"

    required_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [CachedContextSentenceSignal.identifier],
        "attributes": [],
        "documents": []
    }

    generated_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [ContextSentenceEmbeddingSignal.identifier],
        "attributes": [],
        "documents": []
    }

    def __init__(self, bert_resource_identifier: str) -> None:
        """
        Initialize the BERTContextSentenceEmbedder.

        :param bert_resource_identifier: identifier of the BERT model resource
        """
        super(BERTContextSentenceEmbedder, self).__init__()
        self._bert_resource_identifier: str = bert_resource_identifier

        logger.debug(f"Initialized '{self.identifier}'.")

    def _embed_nuggets(
            self,
            nuggets: List[InformationNugget],
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:

        if not nuggets:
            return
        resources.MANAGER.load(self._bert_resource_identifier)
        bert = resources.MANAGER[self._bert_resource_identifier]
        device = bert["device"]
        if device is not None:
            bert["model"].to(device)

        # Process shared contexts together, retaining only one window's hidden states.
        context_groups: Dict[str, List[InformationNugget]] = {}
        for nugget in nuggets:
            context_groups.setdefault(nugget[CachedContextSentenceSignal]["text"], []).append(nugget)
        source_context = None
        output_window = None
        output = None
        limit = 512
        for nugget_ix, nugget in enumerate(nugget for group in context_groups.values() for nugget in group):
            self._use_status_callback_for_embedder(status_callback, "nuggets", nugget_ix, len(nuggets))

            context = nugget[CachedContextSentenceSignal]
            context_sentence = context["text"]
            start_in_context = context["start_char"]
            end_in_context = context["end_char"]
            if context_sentence != source_context:
                encoding = bert["tokenizer"](
                    context_sentence, return_tensors="pt", padding=True, return_offsets_mapping=True
                )
                num_tokens = encoding.input_ids.shape[1]
                token_starts, token_ends = (), ()
                if num_tokens > limit:
                    # WordPiece offsets follow the order of tokens in the source.
                    token_starts, token_ends = zip(*encoding["offset_mapping"][0, 1:-1].tolist())
                source_context = context_sentence
                output_window = None

            # BERT adds [CLS] and [SEP] around the single input sentence.
            window_start, window_end = 1, num_tokens - 1
            if num_tokens > limit:
                statistics["num_too_many_token_indices"] += 1
                mention_start = bisect_right(token_ends, start_in_context) + 1
                mention_end = (bisect_left(token_starts, end_in_context) + 1
                               if end_in_context > start_in_context else mention_start)
                capacity = limit - 2
                mention_length = mention_end - mention_start
                if mention_length > capacity:
                    raise RuntimeError(f"Nugget requires {mention_length} tokens, exceeding BERT's {capacity}-token limit")
                token_indices = range(mention_start, mention_end)
                centered_start = (mention_start + mention_end - capacity) // 2
                window_start = max(1, min(centered_start, window_end - capacity))
                window_end = window_start + capacity
            else:
                token_indices = sorted({
                    encoding.char_to_token(char_ix) for char_ix in range(start_in_context, end_in_context)
                } - {None})

            if (window_start, window_end) != output_window:
                model_inputs = {}
                for name in ("input_ids", "token_type_ids", "attention_mask"):
                    tensor = encoding[name]
                    if num_tokens > limit:
                        tensor = torch.cat((tensor[:, :1], tensor[:, window_start:window_end], tensor[:, -1:]), dim=1)
                    model_inputs[name] = tensor.to(device) if device is not None else tensor
                with torch.inference_mode():
                    output = bert["model"](**model_inputs)[0].detach().cpu()[0].numpy()
                output_window = (window_start, window_end)

            if not token_indices:
                statistics["num_no_token_indices"] += 1
                logger.warning("BERT span has no token indices. Using a zero vector.")
                embedding: np.ndarray = np.zeros_like(output[0])
            else:
                # Offsets refer to the original context. Shift token indices into the model's window.
                window_indices = [ix - window_start + 1 for ix in token_indices]
                embedding = np.mean(output[window_indices], axis=0)
            nugget[ContextSentenceEmbeddingSignal] = ContextSentenceEmbeddingSignal(embedding)

    def to_config(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier,
            "bert_resource_identifier": self._bert_resource_identifier
        }

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "BERTContextSentenceEmbedder":
        return cls(config["bert_resource_identifier"])


@register_configurable_element
class RelativePositionEmbedder(BaseEmbedder):
    """
    Position embedder that embeds the character position of a nugget relative to the start and end of the document.

    works on InformationNuggets:
    required signals: start_char and document.text
    produced signals: RelativePositionSignal
    """
    identifier: str = "RelativePositionEmbedder"

    required_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [],
        "attributes": [],
        "documents": []
    }

    generated_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [RelativePositionSignal.identifier],
        "attributes": [],
        "documents": []
    }

    def __init__(self) -> None:
        super(RelativePositionEmbedder, self).__init__()
        logger.debug(f"Initialized '{self.identifier}'.")

    def _embed_nuggets(
            self,
            nuggets: List[InformationNugget],
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        for ix, nugget in enumerate(nuggets):
            self._use_status_callback_for_embedder(status_callback, "nuggets", ix, len(nuggets))
            if len(nugget.document.text) == 0:
                nugget[RelativePositionSignal] = RelativePositionSignal(0)
                statistics["num_text_is_empty"] += 1
            else:
                relative_position: float = nugget.start_char / len(nugget.document.text)
                nugget[RelativePositionSignal] = RelativePositionSignal(relative_position)

    def to_config(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier
        }

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "RelativePositionEmbedder":
        return cls()


@register_configurable_element
class FastTextLabelEmbedder(BaseEmbedder):
    """
    Label embedder based on FastText.

    Splits the labels by '_' and by spaces and computes the embedding as the mean of the tokens' FastText embeddings.
    """
    identifier: str = "FastTextLabelEmbedder"

    required_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [NaturalLanguageLabelSignal.identifier],
        "attributes": [NaturalLanguageLabelSignal.identifier],
        "documents": []
    }

    generated_signal_identifiers: Dict[str, List[str]] = {
        "nuggets": [LabelEmbeddingSignal.identifier],
        "attributes": [LabelEmbeddingSignal.identifier],
        "documents": []
    }

    def __init__(self, embedding_resource_identifier: str, do_lowercase: bool, splitters: List[str]) -> None:
        """
        Initialize the FastTextLabelEmbedder.

        :param embedding_resource_identifier: identifier of the FastText resource
        :param do_lowercase: whether to lowercase tokens before embedding them
        :param splitters: characters at which the label should be split into tokens
        """
        super(FastTextLabelEmbedder, self).__init__()
        self._embedding_resource_identifier: str = embedding_resource_identifier
        self._do_lowercase: bool = do_lowercase
        self._splitters: List[str] = splitters

        # preload required resources
        resources.MANAGER.load(self._embedding_resource_identifier)
        logger.debug(f"Initialized '{self.identifier}'.")

    def _compute_embedding(self, label: str, statistics: Statistics) -> LabelEmbeddingSignal:
        """
        Compute the embedding of the given label.

        :param label: given label to compute the embedding of
        :param statistics: statistics object to collect statistics
        :return: embedding signal of the label
        """
        # tokenize the label
        tokens: List[str] = [label]
        for splitter in self._splitters:
            new_tokens: List[str] = []
            for token in tokens:
                new_tokens += token.split(splitter)
            tokens: List[str] = new_tokens

        # lowercase the tokens
        if self._do_lowercase:
            tokens: List[str] = [token.lower() for token in tokens]

        # compute the embeddings
        embeddings: List[np.ndarray] = []
        for token in tokens:
            if token in resources.MANAGER[self._embedding_resource_identifier]:
                embeddings.append(resources.MANAGER[self._embedding_resource_identifier][token])
            else:
                statistics["num_unknown_tokens"] += 1
                statistics["unknown_tokens"].add(token)

        if embeddings == []:
            statistics["unable_to_embed_label"] += 1
            logger.error("Unable to embed a label with FastText: no known tokens.")
            assert False, "Unable to embed a label with FastText: no known tokens."
        else:
            # noinspection PyTypeChecker
            return LabelEmbeddingSignal(np.mean(np.array(embeddings), axis=0))

    def _embed_nuggets(
            self,
            nuggets: List[InformationNugget],
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        statistics["unknown_tokens"] = set()

        for ix, nugget in enumerate(nuggets):
            self._use_status_callback_for_embedder(status_callback, "nuggets", ix, len(nuggets))
            label: str = nugget[NaturalLanguageLabelSignal]
            nugget[LabelEmbeddingSignal] = self._compute_embedding(label, statistics)

    def _embed_attributes(
            self,
            attributes: List[Attribute],
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        for ix, attribute in enumerate(attributes):
            self._use_status_callback_for_embedder(status_callback, "attributes", ix, len(attributes))
            label: str = attribute[NaturalLanguageLabelSignal]
            attribute[LabelEmbeddingSignal] = self._compute_embedding(label, statistics)

    def to_config(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier,
            "embedding_resource_identifier": self._embedding_resource_identifier,
            "do_lowercase": self._do_lowercase,
            "splitters": self._splitters
        }

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "FastTextLabelEmbedder":
        return cls(config["embedding_resource_identifier"], config["do_lowercase"], config["splitters"])

import abc
import logging
import os
import time
from subprocess import Popen
from typing import Any, Dict, List, Optional, Type, Union

import numpy as np
import requests
import spacy
import spacy.cli.download
import stanza
import torch
from sentence_transformers import SentenceTransformer
from spacy.language import Language
from stanza import Pipeline
from transformers import BertModel, BertTokenizer, BertTokenizerFast

logger: logging.Logger = logging.getLogger(__name__)

RESOURCES: Dict[str, Type["BaseResource"]] = {}


def register_resource(resource: Type["BaseResource"]) -> Type["BaseResource"]:
    """Register the given resource."""
    RESOURCES[resource.identifier] = resource
    return resource


class BaseResource(abc.ABC):
    """
    Resource that may be used by other elements of the system.

    Resources are capabilities that may be used by other elements of the system. Each resource is a class that describes
    how the resource may be loaded ('load'), accessed ('resource'), and unloaded ('unload'). Each resource comes with an
    identifier ('identifier'). Resources are managed by the resource manager, which can load the same resource once and
    provide it to multiple users and also manages to close all resources when the program ends.
    """

    identifier: str = "BaseResource"

    @classmethod
    @abc.abstractmethod
    def load(cls) -> "BaseResource":
        """Load the resource."""
        raise NotImplementedError

    @abc.abstractmethod
    def unload(self) -> None:
        """Unload the resource."""
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def resource(self) -> Any:
        """Access the resource."""
        raise NotImplementedError


MANAGER: Optional["ResourceManager"] = None


class ResourceManager:
    """
    The resource manager provides the system with access to shared resources (e.g. embeddings).

    It loads the resources when they are requested and ensures that they are closed when the program finishes. The
    resource manager implements the singleton pattern, i.e. there should always be at most one resource manager. The
    resource manager should always be accessed using the resources.MANAGER module variable. To set up the resource
    manager in a program, use it as a Python context manager to make sure that all resources are closed when the
    program finishes.
    """

    def __init__(self) -> None:
        """Initialize the resource manager."""
        global MANAGER

        # check that this is the only resource manager
        if MANAGER is not None:
            logger.error("There can only be one resource manager!")
            assert False, "There can only be one resource manager!"
        else:
            MANAGER = self

        self._resources: Dict[str, BaseResource] = {}

        logger.info("Initialized the resource manager.")

    def __enter__(self) -> "ResourceManager":
        """
        Enter the resource manager context.

        :return: the resource manager itself
        """
        logger.info("Entered the resource manager.")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit the resource manager context."""
        logger.info("Unload all resources.")
        tick: float = time.time()

        # close resources
        for resource_identifier in list(self._resources.keys()):
            self.unload(resource_identifier)

        tack: float = time.time()
        logger.info(f"Unloaded all resources in {tack - tick} seconds.")
        logger.info("Exited the resource manager.")

    def __str__(self) -> str:
        resources_str: str = "\n".join(f"- {resource_identifier}" for resource_identifier in self._resources.keys())
        return "Currently loaded resources:\n{}".format(resources_str if resources_str != "" else " -")

    def load(self, resource: Union[str, Type[BaseResource]]) -> None:
        """
        Load a resource.

        :param resource: resource class or identifier of the resource to load
        """
        if isinstance(resource, str):
            resource_identifier: str = resource
        else:
            resource_identifier: str = resource.identifier

        if resource_identifier not in RESOURCES.keys():
            logger.error(f"Unknown resource '{resource_identifier}'!")
            assert False, f"Unknown resource '{resource_identifier}'!"
        elif resource_identifier in self._resources:
            logger.info(f"Resource '{resource_identifier}' already loaded.")
        else:
            logger.info(f"Load resource '{resource_identifier}'.")
            tick: float = time.time()
            self._resources[resource_identifier] = RESOURCES[resource_identifier].load()
            tack: float = time.time()
            logger.info(f"Loaded resource '{resource_identifier}' in {tack - tick} seconds.")

    def unload(self, resource: Union[str, Type[BaseResource]]) -> None:
        """
        Unload a resource.

        :param resource: resource class or identifier of the resource to load
        """
        if isinstance(resource, str):
            resource_identifier: str = resource
        else:
            resource_identifier: str = resource.identifier

        if resource_identifier not in RESOURCES.keys():
            logger.error(f"Unknown resource '{resource_identifier}'!")
            assert False, f"Unknown resource '{resource_identifier}'!"
        elif resource_identifier not in self._resources:
            logger.error(f"Resource '{resource_identifier}' is not loaded!")
            assert False, f"Resource '{resource_identifier}' is not loaded!"
        else:
            logger.info(f"Unload resource '{resource_identifier}'.")
            tick: float = time.time()
            self._resources[resource_identifier].unload()
            del self._resources[resource_identifier]
            tack: float = time.time()
            logger.info(f"Unloaded resource '{resource_identifier}' in {tack - tick} seconds.")

    def __getitem__(self, resource: Union[str, Type[BaseResource]]) -> Any:
        """
        Access a resource.

        :param resource: resource class or identifier of the resource to load
        :return: the resource
        """
        if isinstance(resource, str):
            resource_identifier: str = resource
        else:
            resource_identifier: str = resource.identifier

        if resource_identifier not in RESOURCES.keys():
            logger.error(f"Unknown resource '{resource_identifier}'!")
            assert False, f"Unknown resource '{resource_identifier}'!"
        elif resource_identifier not in self._resources:
            logger.error(f"Resource '{resource_identifier}' is not loaded!")
            assert False, f"Resource '{resource_identifier}' is not loaded!"
        else:
            return self._resources[resource_identifier].resource


########################################################################################################################
# actual resources
########################################################################################################################


@register_resource
class StanzaNERPipeline(BaseResource):
    """
    Stanza pipeline for named entity recognition.

    See https://stanfordnlp.github.io/stanza/
    """

    identifier: str = "StanzaNERPipeline"

    def __init__(self) -> None:
        """Initialize the StanzaNERPipeline."""
        super(StanzaNERPipeline, self).__init__()
        path: str = os.path.join(os.path.dirname(__file__), "..", "models", "stanza")
        self._stanza_ner_pipeline: Pipeline = Pipeline(
            lang="en", processors="tokenize,mwt,pos,ner", model_dir=path, verbose=False
        )

    @classmethod
    def load(cls) -> "StanzaNERPipeline":
        # download the stanza resources if necessary
        path: str = os.path.join(os.path.dirname(__file__), "..", "models", "stanza")
        os.makedirs(path, exist_ok=True)
        path: str = os.path.join(os.path.dirname(__file__), "..", "models", "stanza", "en")
        if not os.path.isdir(path):
            path: str = os.path.join(os.path.dirname(__file__), "..", "models", "stanza")
            logger.info("Download the stanza 'en' language package.")
            stanza.download("en", path)
        return cls()

    def unload(self) -> None:
        del self._stanza_ner_pipeline

    @property
    def resource(self) -> Pipeline:
        return self._stanza_ner_pipeline


class BaseFastTextEmbedding(BaseResource, abc.ABC):
    """
    Base class for all FastText embeddings.

    See https://fasttext.cc/
    """

    identifier: str = "BaseFastTextEmbedding"
    _num_vectors: Optional[int] = None

    def __init__(self) -> None:
        """Initialize the FastText embedding."""
        super(BaseFastTextEmbedding, self).__init__()
        self._fast_text_embedding: Dict[str, np.ndarray] = {}
        path: str = os.path.join(os.path.dirname(__file__), "..", "models", "fasttext", "wiki-news-300d-1M-subword.vec")
        with open(path, "r", encoding="utf-8", newline="\n", errors="ignore") as file:
            _ = file.readline()  # skip number of words, dimension
            n: int = 0
            for line in file:
                if self._num_vectors is not None and n >= self._num_vectors:
                    break
                n += 1
                parts: List[str] = line.rstrip().split(" ")
                self._fast_text_embedding[parts[0]] = np.array([float(part) for part in parts[1:]])

    @classmethod
    def load(cls) -> "BaseFastTextEmbedding":
        # check that the FastText model has been downloaded
        path: str = os.path.join(os.path.dirname(__file__), "..", "models", "fasttext")
        os.makedirs(path, exist_ok=True)
        path: str = os.path.join(os.path.dirname(__file__), "..", "models", "fasttext", "wiki-news-300d-1M-subword.vec")
        if not os.path.isfile(path):
            logger.error("You have to download the model by hand and place it in the appropriate folder!")
            logger.error("URL: https://fasttext.cc/docs/en/english-vectors.html")
            assert False, "You have to download the model by hand and place it in the appropriate folder!"
        return cls()

    def unload(self) -> None:
        del self._fast_text_embedding

    @property
    def resource(self) -> Dict[str, np.ndarray]:
        return self._fast_text_embedding


@register_resource
class FastTextEmbedding100000(BaseFastTextEmbedding):
    """FastText embedding that includes only the 100000 first vectors."""

    identifier: str = "FastTextEmbedding100000"
    _num_vectors: Optional[int] = 100000


@register_resource
class FastTextEmbedding(BaseFastTextEmbedding):
    """FastText embedding that includes all vectors."""

    identifier: str = "FastTextEmbedding"
    _num_vectors: Optional[int] = None


class BaseSpacyResource(BaseResource, abc.ABC):
    """
    Base class for all spacy-based resources.

    See https://spacy.io/
    """

    identifier: str = "BaseSpacyResource"
    _spacy_package_str: str = "BaseSpacyPackageStr"

    def __init__(self) -> None:
        """Initialize the spacy model."""
        super(BaseSpacyResource, self).__init__()
        self._spacy_nlp: Language = spacy.load(self._spacy_package_str)

    @classmethod
    def load(cls) -> "BaseSpacyResource":
        # download the spacy model if necessary
        if not spacy.util.is_package(cls._spacy_package_str):
            logger.info(f"Download the spacy package '{cls._spacy_package_str}'.")
            spacy.cli.download(cls._spacy_package_str)
            logger.error("Interpreter must be restarted after installing spacy package.")
            assert False, "Interpreter must be restarted after installing spacy package."

        return cls()

    def unload(self) -> None:
        del self._spacy_nlp

    @property
    def resource(self) -> Language:
        return self._spacy_nlp


@register_resource
class SpacyEnCoreWebTrf(BaseSpacyResource):
    """Spacy 'en_core_web_trf' model."""

    identifier: str = "SpacyEnCoreWebTrf"
    _spacy_package_str: str = "en_core_web_trf"


@register_resource
class SpacyEnCoreWebLg(BaseSpacyResource):
    """Spacy 'en_core_web_lg' model."""

    identifier: str = "SpacyEnCoreWebLg"
    _spacy_package_str: str = "en_core_web_lg"


@register_resource
class SpacyEnCoreWebMd(BaseSpacyResource):
    """Spacy 'en_core_web_md' model."""

    identifier: str = "SpacyEnCoreWebMd"
    _spacy_package_str: str = "en_core_web_md"


@register_resource
class SpacyEnCoreWebSm(BaseSpacyResource):
    """Spacy 'en_core_web_sm' model."""

    identifier: str = "SpacyEnCoreWebSm"
    _spacy_package_str: str = "en_core_web_sm"


@register_resource
class SpacyEnCoreSciMd(BaseResource):
    """
    Spacy 'en_core_sci_md' model.

    See https://allenai.github.io/scispacy/
    """

    identifier: str = "SpacyEnCoreSciMd"

    def __init__(self) -> None:
        """Initialize the spacy model."""
        super(BaseResource, self).__init__()
        path: str = os.path.join(os.path.dirname(__file__), "..", "models", "spacy", "en_core_sci_md-0.4.0",
                                 "en_core_sci_md", "en_core_sci_md-0.4.0")
        self._spacy_nlp: Language = spacy.load(path)

    @classmethod
    def load(cls) -> "SpacyEnCoreSciMd":
        # check that the spacy model has been downloaded
        path: str = os.path.join(os.path.dirname(__file__), "..", "models", "spacy")
        os.makedirs(path, exist_ok=True)
        path: str = os.path.join(os.path.dirname(__file__), "..", "models", "spacy", "en_core_sci_md-0.4.0")
        if not os.path.isdir(path):
            logger.error("You have to download the model by hand and place it in the appropriate folder!")
            assert False, "You have to download the model by hand and place it in the appropriate folder!"
        return cls()

    def unload(self) -> None:
        del self._spacy_nlp

    @property
    def resource(self) -> Language:
        return self._spacy_nlp


@register_resource
class SpacyEnNerCraftMd(BaseResource):
    """
    Spacy 'en_ner_craft_md' model.

    See https://allenai.github.io/scispacy/
    """

    identifier: str = "SpacyEnNerCraftMd"

    def __init__(self) -> None:
        """Initialize the spacy model."""
        super(BaseResource, self).__init__()
        path: str = os.path.join(os.path.dirname(__file__), "..", "models", "spacy", "en_ner_craft_md-0.4.0",
                                 "en_ner_craft_md", "en_ner_craft_md-0.4.0")
        self._spacy_nlp: Language = spacy.load(path)

    @classmethod
    def load(cls) -> "SpacyEnNerCraftMd":
        # check that the spacy model has been downloaded
        path: str = os.path.join(os.path.dirname(__file__), "..", "models", "spacy")
        os.makedirs(path, exist_ok=True)
        path: str = os.path.join(os.path.dirname(__file__), "..", "models", "spacy", "en_ner_craft_md-0.4.0")
        if not os.path.isdir(path):
            logger.error("You have to download the spacy model by hand and place it in the appropriate folder!")
            assert False, "You have to download the spacy model by hand and place it in the appropriate folder!"
        return cls()

    def unload(self) -> None:
        del self._spacy_nlp

    @property
    def resource(self) -> Language:
        return self._spacy_nlp


class BaseBERTResource(BaseResource):
    """
    Base class for all BERT-based resources.

    See https://huggingface.co/transformers/model_doc/bert.html
    """

    identifier: str = "BaseBERTResource"
    _bert_model_str: str = "BaseBertModelStr"

    def __init__(self) -> None:
        """Initialize the BERT resource."""
        super(BaseBERTResource, self).__init__()
        path: str = os.path.join(os.path.dirname(__file__), "..", "models", "transformers")

        self._tokenizer: BertTokenizer = BertTokenizerFast.from_pretrained(self._bert_model_str, cache_dir=path)
        self._tokenizer.add_tokens(["[START_MENTION]", "[END_MENTION]", "[MASK]"])

        self._model: BertModel = BertModel.from_pretrained(self._bert_model_str, cache_dir=path)

        # Use GPU for BERT model, but only if there is enough GPU RAM available
        if torch.cuda.is_available() and torch.cuda.get_device_properties(0).total_memory > 4 * 1024 * 1024 * 1024:
            self._device: Optional[Any] = torch.device("cuda")
            logger.info(f"Will use GPU for BERT model")
        else:
            self._device: Optional[Any] = None

    @classmethod
    def load(cls) -> "BaseBERTResource":
        path: str = os.path.join(os.path.dirname(__file__), "..", "models", "transformers")
        os.makedirs(path, exist_ok=True)
        return cls()

    def unload(self) -> None:
        del self._tokenizer
        del self._model
        del self._device

    @property
    def resource(self) -> Dict[str, Any]:
        return {
            "tokenizer": self._tokenizer,
            "model": self._model,
            "device": self._device
        }


@register_resource
class BertLargeCasedResource(BaseBERTResource):
    """BERT 'bert-large-cased' model."""

    identifier: str = "BertLargeCasedResource"
    _bert_model_str: str = "bert-large-cased"


class BaseSBERTResource(BaseResource, abc.ABC):
    """
    Base class for all SBERT-based resources.

    See https://sbert.net/
    """

    identifier: str = "BaseSBERTResource"
    _sbert_model_str: str = "BaseSBERTModelStr"

    def __init__(self) -> None:
        """Initialize the SBERT resource."""
        super(BaseSBERTResource, self).__init__()

        path: str = os.path.join(os.path.dirname(__file__), "..", "models", "sentence-transformers")
        self._sbert_model: SentenceTransformer = SentenceTransformer(self._sbert_model_str, cache_folder=path)

    @classmethod
    def load(cls) -> "BaseSBERTResource":
        path: str = os.path.join(os.path.dirname(__file__), "..", "models", "sentence-transformers")
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
        return cls()

    def unload(self) -> None:
        del self._sbert_model

    @property
    def resource(self) -> SentenceTransformer:
        return self._sbert_model


@register_resource
class SBERTBertLargeNliMeanTokensResource(BaseSBERTResource):
    """SBERT 'bert-large-nli-mean-tokens' model."""

    identifier: str = "SBERTBertLargeNliMeanTokensResource"
    _sbert_model_str: str = "bert-large-nli-mean-tokens"


@register_resource
class SBERTAllMiniLML6v2Resource(BaseSBERTResource):
    """SBERT 'all-MiniLM-L6-v2' model."""

    identifier: str = "SBERTAllMiniLML6v2Resource"
    _sbert_model_str: str = "all-MiniLM-L6-v2"


@register_resource
class GloveEmbeddings300(BaseResource):
    """ Glove Embeddings 840B 300d"""

    identifier: str = "GloveEmbedding300"

    def __init__(self) -> None:
        """Initialize the GloVe resource"""
        super(GloveEmbeddings300, self).__init__()
        vocab_path: str = os.path.join(os.path.dirname(__file__), "..", "models", "glove", "glove.840B.300d.vocab")
        vector_path: str = os.path.join(os.path.dirname(__file__), "..", "models", "glove", "glove.840B.300dvectors.npy")

        with open(vocab_path, 'r', encoding='utf-8') as file:
            self._index2word: List = [line.rstrip("\n") for line in file]
        vectors_memmap: np.memmap = np.memmap(vector_path, dtype="float32", mode="r")
        self._vectors_memmap = vectors_memmap.reshape(-1, 300)
        embedding_vector = {}
        assert (len(self._index2word) == len(self._vectors_memmap))
        for i, w in enumerate(self._index2word):
            embedding_vector[w] = vectors_memmap[i]

        print(f"Loaded {len(embedding_vector)} word vectors.")

        self._word2index: Dict = dict(map(reversed, enumerate(self._index2word)))

        print("Done loading embeddings.")

    @classmethod
    def load(cls) -> "GloveEmbeddings300":
        # check that the GloVe embeddings have been downloaded
        path: str = os.path.join(os.path.dirname(__file__), "..", "models", "glove")
        os.makedirs(path, exist_ok=True)
        vocab_path: str = os.path.join(os.path.dirname(__file__), "..", "models", "glove", "glove.840B.300d.vocab")
        vector_path: str = os.path.join(os.path.dirname(__file__), "..", "models", "glove", "glove.840B.300dvectors.npy")
        if not os.path.isfile(vocab_path):
            logger.error("Missing file glove.840B.300d.vocab. You have to download the glove embeddings by hand and place them in the 'models/glove' folder!")
            assert False, "Missing file glove.840B.300d.vocab. You have to download the glove embeddings by hand and place them in the 'models/glove' folder!"
        if not os.path.isfile(vector_path):
            logger.error("Missing file glove.840B.300dvectors.npy. You have to download the glove embeddings by hand and place them in the 'models/glove' folder!")
            assert False, "Missing file glove.840B.300dvectors.npy. You have to download the glove embeddings by hand and place them in the 'models/glove' folder!"
        return cls()

    def unload(self) -> None:
        del self._word2index
        del self._index2word
        del self._vectors_memmap

    @property
    def resource(self) -> Dict[str, Any]:
        return {
            "word2index": self._word2index,
            "index2word": self._index2word,
            "vectors_memmap": self._vectors_memmap
        }


@register_resource
class FigerNERPipeline(BaseResource):
    """
    Adapted FIGER fine graned entity recognizer

    See https://github.com/DataManagementLab/figer/tree/update-dependencies/project
    """

    identifier: str = "FigerAPI"
    _url: str = ""
    _managed: bool = False

    def __init__(self, url) -> None:
        """Initialize the FigerNERPipeline."""
        super().__init__()
        self._url = url

        # Check whether FIGER is already running
        try:
            r = requests.get(url)
            r.raise_for_status()  # Raises a HTTPError if the status is 4xx, 5xxx
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            # Load server as managed background process
            self._background_process = Popen(["./models/figer2/sbt", "~jetty:start"])
            self._managed = True

    @classmethod
    def load(cls) -> "FigerNERPipeline":
        url = "http://localhost:8081/api"
        return cls(url)

    def unload(self) -> None:
        # Stop FIGER server if WannaDB is responsible
        if self._managed:
            self._background_process.terminate()

    @property
    def resource(self) -> str:
        return self._url

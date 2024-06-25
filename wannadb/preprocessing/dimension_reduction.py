import logging
from abc import ABC
from typing import Dict, Any

from numpy import ndarray
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE

from wannadb.configuration import BasePipelineElement, register_configurable_element
from wannadb.data.data import DocumentBase
from wannadb.data.signals import LabelEmbeddingSignal, TextEmbeddingSignal, PCADimensionReducedLabelEmbeddingSignal, \
    PCADimensionReducedTextEmbeddingSignal, TSNEDimensionReducedLabelEmbeddingSignal, \
    TSNEDimensionReducedTextEmbeddingSignal
from wannadb.interaction import BaseInteractionCallback
from wannadb.statistics import Statistics
from wannadb.status import BaseStatusCallback

logger = logging.getLogger(__name__)


class DimensionReducer(BasePipelineElement, ABC):
    identifier: str = "DimensionReducer"

    def __init__(self):
        super(DimensionReducer, self).__init__()

    def _call(self, document_base: DocumentBase, interaction_callback: BaseInteractionCallback,
              status_callback: BaseStatusCallback, statistics: Statistics) -> None:
        pass

    def reduce_dimensions(self, data) -> ndarray:
        pass


@register_configurable_element
class PCAReducer(DimensionReducer):
    identifier: str = "PCAReducer"

    def __init__(self):
        super().__init__()
        self.pca = PCA(n_components=3)

    def __call__(
            self,
            document_base: DocumentBase,
            interaction_callback: BaseInteractionCallback,
            status_callback: BaseStatusCallback,
            statistics: Statistics
    ) -> None:
        #Assume that all embeddings have same number of features
        attribute_embeddings = [attribute[LabelEmbeddingSignal] for attribute in document_base.attributes]
        nugget_embeddings = [nugget[TextEmbeddingSignal] for nugget in document_base.nuggets]
        all_embeddings = attribute_embeddings + nugget_embeddings

        if len(all_embeddings) < 3:
            logger.warning("Not enough data to apply dimension reduction, will not compute them.")
            return

        dimension_reduced_embeddings = self.reduce_dimensions(all_embeddings)

        for idx, embedding in enumerate(dimension_reduced_embeddings):
            if idx < len(attribute_embeddings):
                document_base.attributes[idx][PCADimensionReducedLabelEmbeddingSignal] = (
                    PCADimensionReducedLabelEmbeddingSignal(embedding))
            else:
                document_base.nuggets[idx - len(attribute_embeddings)][PCADimensionReducedTextEmbeddingSignal] = (
                    PCADimensionReducedTextEmbeddingSignal(embedding))

    def reduce_dimensions(self, data) -> ndarray:
        self.pca.fit(data)
        return self.pca.transform(data)

    def to_config(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier
        }

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "DimensionReducer":
        return cls()


@register_configurable_element
class TSNEReducer(DimensionReducer):
    identifier: str = "TSNEReducer"

    def __init__(self):
        super().__init__()
        self.tsne = TSNE(n_components=3, n_iter=300)

    def _call(self, document_base: DocumentBase, interaction_callback: BaseInteractionCallback,
              status_callback: BaseStatusCallback, statistics: Statistics) -> None:
        attribute_embeddings = [attribute[LabelEmbeddingSignal] for attribute in document_base.attributes]
        nugget_embeddings = [nugget[TextEmbeddingSignal] for nugget in document_base.nuggets]
        all_embeddings = attribute_embeddings + nugget_embeddings

        dimension_reduced_embeddings = self.reduce_dimensions(all_embeddings)

        for idx, embedding in enumerate(dimension_reduced_embeddings):
            if idx < len(attribute_embeddings):
                document_base.attributes[idx][TSNEDimensionReducedLabelEmbeddingSignal] = (
                    TSNEDimensionReducedLabelEmbeddingSignal(embedding))
            else:
                document_base.nuggets[idx - len(attribute_embeddings)][TSNEDimensionReducedTextEmbeddingSignal] = (
                    TSNEDimensionReducedTextEmbeddingSignal(embedding))

    def reduce_dimensions(self, data) -> ndarray:
        return self.tsne.fit_transform(data)

    def to_config(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier
        }

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "DimensionReducer":
        return cls()

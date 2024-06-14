from numpy import ndarray
from sklearn.decomposition import PCA


class PCAReduction:

    def __init__(self):
        self.pca = PCA(n_components=3)

    def reduce_dimensions(self, data) -> ndarray:
        return self.pca.fit_transform(data)

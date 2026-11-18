"""Recommendation baseline: frequently bought together.

Counts how often each pair of products shared a basket on the training period. For a
query, every candidate scores the sum of its co-purchase counts with the products already
in the basket; overall popularity breaks ties (and fills in when nothing co-occurs).
"""

import numpy as np
from scipy import sparse

from feature_engineering.interaction_features import Baskets


class FrequentlyBoughtTogether:
    def fit(self, baskets: Baskets) -> "FrequentlyBoughtTogether":
        rows = np.repeat(np.arange(len(baskets.items)), [len(i) for i in baskets.items])
        cols = np.concatenate(baskets.items) if baskets.items else np.array([], int)
        matrix = sparse.csr_matrix(
            (np.ones(len(cols)), (rows, cols)), shape=(len(baskets.items), baskets.products + 1)
        )
        co = (matrix.T @ matrix).toarray()
        np.fill_diagonal(co, 0)
        self.co = co
        self.popularity = np.asarray(matrix.sum(axis=0)).ravel()
        return self

    def scores(self, inputs: dict[str, np.ndarray]) -> np.ndarray:
        """(queries, products + 1) scores; column 0 is padding."""
        context = inputs["context"]
        total = self.co[context].sum(axis=1)  # padding row 0 is all zeros
        total -= self.co[0][None, :] * (context == 0).sum(axis=1, keepdims=True)
        tie_break = self.popularity / max(self.popularity.max(), 1) * 1e-3
        return total + tie_break[None, :]

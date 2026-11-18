"""Delay baseline: logistic regression on the same numbers and categories the networks
get (standardised), fitted on the training period. A straight line in log-odds: it can
add up risk factors but not combine them."""

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler


class LogisticBaseline:
    def __init__(self, seed: int = 0) -> None:
        self.scaler = StandardScaler()
        self.model = LogisticRegression(max_iter=1000, random_state=seed)

    def fit(self, numeric: np.ndarray, categorical: np.ndarray, label: np.ndarray):
        x = np.hstack([self.scaler.fit_transform(numeric), categorical])
        self.model.fit(x, label)
        return self

    def predict(self, inputs: dict[str, np.ndarray]) -> np.ndarray:
        x = np.hstack([self.scaler.transform(inputs["numeric"]), inputs["categorical"]])
        return self.model.predict_proba(x)[:, 1]

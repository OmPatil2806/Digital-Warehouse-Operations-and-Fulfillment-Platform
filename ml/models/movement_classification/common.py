"""Shared parts: encoder, decoder, the cluster assignment layer and the exported model."""

from dataclasses import dataclass

import keras
import numpy as np
from keras import ops
from sklearn.cluster import KMeans


@keras.saving.register_keras_serializable(package="warehouse")
class ClusterAssignment(keras.layers.Layer):
    """Soft assignment of embeddings to cluster centres (Student's t kernel, as in DEC):
    q_ij is high when point i is close to centre j; each row sums to 1."""

    def __init__(self, clusters: int, alpha: float = 1.0, **kwargs) -> None:
        super().__init__(**kwargs)
        self.clusters, self.alpha = clusters, alpha

    def build(self, input_shape) -> None:
        self.centres = self.add_weight(
            shape=(self.clusters, input_shape[-1]), initializer="glorot_uniform", name="centres"
        )

    def call(self, z):
        distance = ops.sum(ops.square(ops.expand_dims(z, 1) - self.centres), axis=2)
        q = ops.power(1.0 + distance / self.alpha, -(self.alpha + 1.0) / 2.0)
        return q / ops.sum(q, axis=1, keepdims=True)

    def get_config(self) -> dict:
        return {**super().get_config(), "clusters": self.clusters, "alpha": self.alpha}


def encoder(dim: int, hidden: list[int], latent: int, name: str = "encoder") -> keras.Model:
    x = inputs = keras.Input((dim,))
    for width in hidden:
        x = keras.layers.Dense(width, activation="relu")(x)
    return keras.Model(inputs, keras.layers.Dense(latent)(x), name=name)


def decoder(latent: int, hidden: list[int], dim: int) -> keras.Model:
    x = inputs = keras.Input((latent,))
    for width in reversed(hidden):
        x = keras.layers.Dense(width, activation="relu")(x)
    return keras.Model(inputs, keras.layers.Dense(dim)(x), name="decoder")


def kmeans(embedding: np.ndarray, clusters: int, seed: int) -> KMeans:
    return KMeans(n_clusters=clusters, n_init=10, random_state=seed).fit(embedding)


@dataclass
class Clusterer:
    """Raw features -> cluster probabilities (normalisation and centres inside)."""

    model: keras.Model
    epochs: int

    def probabilities(self, features: np.ndarray) -> np.ndarray:
        return self.model.predict(np.asarray(features, "float32"), verbose=0)

    def labels(self, features: np.ndarray) -> np.ndarray:
        return self.probabilities(features).argmax(axis=1)


def export(
    embed: keras.Model, centres: np.ndarray, mean: np.ndarray, variance: np.ndarray, name: str
) -> keras.Model:
    """One model from raw features: standardise -> embed -> assign to the centres."""
    inputs = keras.Input((len(mean),), name="features")
    norm = keras.layers.Normalization(mean=mean, variance=variance)
    assign = ClusterAssignment(len(centres), name="clusters")
    output = assign(embed(norm(inputs)))
    assign.centres.assign(centres.astype("float32"))
    return keras.Model(inputs, output, name=name)

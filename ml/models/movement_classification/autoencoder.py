"""Autoencoder + K-Means: the network learns to squeeze the product features into a few
numbers and rebuild them; K-Means then groups products in that compressed space."""

import keras
import numpy as np

from models.movement_classification.common import Clusterer, decoder, encoder, export, kmeans


def fit(x: np.ndarray, params: dict, seed: int, mean: np.ndarray, variance: np.ndarray):
    """`x` standardised training features."""
    keras.utils.set_random_seed(seed)
    hidden, latent = params.get("hidden", [16, 8]), params.get("latent", 3)
    enc = encoder(x.shape[1], hidden, latent)
    auto = keras.Sequential([enc, decoder(latent, hidden, x.shape[1])])
    auto.compile(optimizer=keras.optimizers.Adam(params.get("learning_rate", 0.005)), loss="mse")
    epochs = params.get("epochs", 150)
    auto.fit(x, x, epochs=epochs, batch_size=params.get("batch_size", 64), verbose=0)
    centres = kmeans(enc.predict(x, verbose=0), params.get("clusters", 3), seed).cluster_centers_
    return Clusterer(export(enc, centres, mean, variance, "autoencoder_kmeans"), epochs)

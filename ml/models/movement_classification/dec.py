"""Deep Embedded Clustering (Xie et al., 2016): an autoencoder is pre-trained, K-Means
gives the first cluster centres, then encoder and centres are trained together so the
soft assignments sharpen towards confident groups (KL divergence to a target
distribution that emphasises high-confidence points)."""

import keras
import numpy as np
import tensorflow as tf

from models.movement_classification.common import (
    ClusterAssignment,
    Clusterer,
    decoder,
    encoder,
    export,
    kmeans,
)


def target_distribution(q: np.ndarray) -> np.ndarray:
    """p_ij = q_ij^2 / f_j, normalised per row (f_j = cluster frequency)."""
    weight = q**2 / q.sum(axis=0)
    return weight / weight.sum(axis=1, keepdims=True)


def fit(x: np.ndarray, params: dict, seed: int, mean: np.ndarray, variance: np.ndarray):
    keras.utils.set_random_seed(seed)
    hidden, latent = params.get("hidden", [16, 8]), params.get("latent", 3)
    clusters = params.get("clusters", 3)
    enc = encoder(x.shape[1], hidden, latent)
    auto = keras.Sequential([enc, decoder(latent, hidden, x.shape[1])])
    auto.compile(optimizer=keras.optimizers.Adam(params.get("learning_rate", 0.005)), loss="mse")
    pretrain = params.get("pretrain_epochs", 100)
    auto.fit(x, x, epochs=pretrain, batch_size=params.get("batch_size", 64), verbose=0)

    assign = ClusterAssignment(clusters)
    assign.build((None, latent))
    assign.centres.assign(kmeans(enc.predict(x, verbose=0), clusters, seed).cluster_centers_)
    optimizer = keras.optimizers.Adam(params.get("cluster_learning_rate", 0.001))
    data = x.astype("float32")
    rounds = params.get("rounds", 20)
    for _ in range(rounds):
        p = target_distribution(assign(enc(data)).numpy())
        for _ in range(params.get("steps_per_round", 10)):
            with tf.GradientTape() as tape:
                q = assign(enc(data, training=True))
                loss = tf.reduce_sum(p * tf.math.log((p + 1e-9) / (q + 1e-9))) / len(data)
            weights = enc.trainable_weights + assign.trainable_weights
            optimizer.apply_gradients(zip(tape.gradient(loss, weights), weights, strict=True))
    centres = assign.centres.numpy()
    return Clusterer(export(enc, centres, mean, variance, "dec"), pretrain + rounds)

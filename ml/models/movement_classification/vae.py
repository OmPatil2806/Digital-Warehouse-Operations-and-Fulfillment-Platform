"""Variational Autoencoder + K-Means: like the autoencoder, but each product becomes a small
cloud (mean and spread) in the compressed space, which keeps that space smooth; K-Means
groups the cloud centres."""

import keras
import numpy as np
import tensorflow as tf

from models.movement_classification.common import Clusterer, decoder, encoder, export, kmeans


@keras.saving.register_keras_serializable(package="warehouse")
class MeanPart(keras.layers.Layer):
    """The first `latent` encoder outputs (the means; the rest are log-variances)."""

    def __init__(self, latent: int, **kwargs) -> None:
        super().__init__(**kwargs)
        self.latent = latent

    def call(self, stats):
        return stats[:, : self.latent]

    def get_config(self) -> dict:
        return {**super().get_config(), "latent": self.latent}


def fit(x: np.ndarray, params: dict, seed: int, mean: np.ndarray, variance: np.ndarray):
    keras.utils.set_random_seed(seed)
    hidden, latent = params.get("hidden", [16, 8]), params.get("latent", 3)
    enc = encoder(x.shape[1], hidden, latent * 2, name="vae_encoder")  # mean and log-variance
    dec = decoder(latent, hidden, x.shape[1])
    optimizer = keras.optimizers.Adam(params.get("learning_rate", 0.005))
    beta = params.get("beta", 0.1)  # weight of the KL term
    data = tf.data.Dataset.from_tensor_slices(x.astype("float32"))
    epochs = params.get("epochs", 150)
    generator = tf.random.Generator.from_seed(seed)
    weights = enc.trainable_weights + dec.trainable_weights
    optimizer.build(weights)

    @tf.function  # compiled once: much faster than running each step eagerly
    def step(batch):
        with tf.GradientTape() as tape:
            stats = enc(batch, training=True)
            z_mean, z_log_var = stats[:, :latent], stats[:, latent:]
            z = z_mean + tf.exp(0.5 * z_log_var) * generator.normal(tf.shape(z_mean))
            rebuilt = dec(z, training=True)
            reconstruction = tf.reduce_mean(tf.reduce_sum(tf.square(batch - rebuilt), 1))
            kl = -0.5 * tf.reduce_mean(
                tf.reduce_sum(1 + z_log_var - tf.square(z_mean) - tf.exp(z_log_var), 1)
            )
            loss = reconstruction + beta * kl
        optimizer.apply_gradients(zip(tape.gradient(loss, weights), weights, strict=True))
        return loss

    for _ in range(epochs):
        for batch in data.shuffle(len(x), seed=seed).batch(params.get("batch_size", 64)):
            step(batch)
    # The embedding used for clustering is the mean of each product's cloud.
    full = keras.Model(enc.input, MeanPart(latent)(enc.output), name="vae_mean_encoder")
    centres = kmeans(full.predict(x, verbose=0), params.get("clusters", 3), seed).cluster_centers_
    return Clusterer(export(full, centres, mean, variance, "vae_kmeans"), epochs)

"""Movement classification: representation learning + clustering into fast, medium and
slow movers (Autoencoder + K-Means, Variational Autoencoder + K-Means, Deep Embedded
Clustering). Each method returns a saved Keras model mapping raw product features to
cluster probabilities."""

from models.movement_classification import autoencoder, dec, vae

METHODS = {"autoencoder_kmeans": autoencoder.fit, "vae_kmeans": vae.fit, "dec": dec.fit}

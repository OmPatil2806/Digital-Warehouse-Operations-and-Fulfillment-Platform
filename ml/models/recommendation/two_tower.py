"""Two-Tower retrieval: a query tower (basket, history, customer) and a product tower
(product and its category) each map to a vector; the score is their dot product. All
products are scored at once, trained with a softmax over the whole catalogue (the
retrieval set-up of TensorFlow Recommenders, written in plain Keras 3)."""

import keras
from keras import ops

from models.recommendation.common import query_inputs, query_vector


@keras.saving.register_keras_serializable(package="warehouse")
class CatalogScores(keras.layers.Layer):
    """Product tower over the whole catalogue, then query . product for every product."""

    def __init__(self, categories: list[int], width: int, dim: int, **kwargs) -> None:
        super().__init__(**kwargs)
        self.categories, self.width, self.dim = list(categories), width, dim
        self.items = keras.layers.Embedding(len(self.categories), width)
        self.category = keras.layers.Embedding(max(self.categories) + 1, width // 2)
        self.tower = keras.layers.Dense(dim)

    def call(self, query):
        ids = ops.arange(len(self.categories))
        cats = ops.convert_to_tensor(self.categories)
        products = self.tower(ops.concatenate([self.items(ids), self.category(cats)], axis=-1))
        return ops.matmul(query, ops.transpose(products))

    def get_config(self) -> dict:
        return {
            **super().get_config(),
            "categories": self.categories,
            "width": self.width,
            "dim": self.dim,
        }


def build(shapes: dict, params: dict, learning_rate: float) -> keras.Model:
    width, dim = params.get("embedding", 32), params.get("dim", 32)
    x = query_inputs()
    items = keras.layers.Embedding(shapes["products"] + 1, width)
    customers = keras.layers.Embedding(shapes["customers"] + 1, width)
    query = keras.layers.Dense(params.get("hidden", 64), activation="relu")(
        query_vector(x, items, customers)
    )
    query = keras.layers.Dense(dim)(query)
    logits = CatalogScores(shapes["categories"], width, dim, name="scores")(query)
    model = keras.Model(x, logits, name="two_tower")
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate),
        loss=keras.losses.SparseCategoricalCrossentropy(from_logits=True),
    )
    return model

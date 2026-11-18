"""Neural Collaborative Filtering (He et al., 2017, NeuMF): the query (basket, history,
customer) and a candidate product meet in two ways, an element-wise product of their
vectors (GMF) and an MLP on both; a sigmoid gives the chance the candidate is the one
added. Trained on the held-out product against random other products."""

import keras

from models.recommendation.common import candidate_input, query_inputs, query_vector


def build(shapes: dict, params: dict, learning_rate: float) -> keras.Model:
    width = params.get("embedding", 32)
    x = {**query_inputs(), "candidate": candidate_input()}
    items = keras.layers.Embedding(shapes["products"] + 1, width)
    customers = keras.layers.Embedding(shapes["customers"] + 1, width)
    query = keras.layers.Dense(width)(query_vector(x, items, customers))
    candidate = items(x["candidate"])
    gmf = keras.layers.Multiply()([query, candidate])
    mlp = keras.layers.Concatenate()([query, candidate])
    for units in params.get("units", [64, 32]):
        mlp = keras.layers.Dense(units, activation="relu")(mlp)
    output = keras.layers.Dense(1, activation="sigmoid", name="score")(
        keras.layers.Concatenate()([gmf, mlp])
    )
    model = keras.Model(x, output, name="ncf")
    model.compile(optimizer=keras.optimizers.Adam(learning_rate), loss="binary_crossentropy")
    return model

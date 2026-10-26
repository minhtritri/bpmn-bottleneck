"""Public-score regression for the BLAS -1 issue documented in Gensim PR #3668.

Two opposite Huffman leaves imply score symmetry under a sign change. This
tests the installed binary, not merely whether the source declaration was edited.
"""

import numpy as np
import pytest
from gensim.models import Word2Vec


@pytest.mark.parametrize("sg", [0, 1])
@pytest.mark.parametrize("dimensions", [1, 4])
def test_installed_word2vec_preserves_negative_one_dot(sg, dimensions):
    model = Word2Vec(vector_size=dimensions, min_count=1, hs=1, negative=0, sg=sg, workers=1, window=1)
    sentence = [["left", "right"]]
    model.build_vocab(sentence)
    model.wv.vectors.fill(0)
    model.wv.vectors[:, 0] = 1
    model.syn1.fill(0)
    control = model.score(sentence, total_sentences=1)
    scores = []
    for sign in [1, -1]:
        model.syn1[:, 0] = sign
        scores.append(model.score(sentence, total_sentences=1))
    np.testing.assert_allclose(scores[0], scores[1], atol=1e-7)
    assert scores[1][0] < control[0]

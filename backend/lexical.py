"""Tokenización y BM25 en memoria (sin dependencias externas)."""
import math
import re
import unicodedata
from collections import Counter

import numpy as np

STOPWORDS = set(
    "a al algo ante como con como cual cuales cuando de del donde el ella ellos en es esa ese eso esta este esto "
    "hay la las le les lo los mas me mi mis muy no nos o para pero por que se si sin sobre su sus te tu tus un "
    "una uno unos y ya yo son ser fue puede pueden hacer tiene tienen quiero quisiera".split()
)


def tokenize(text: str):
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return [t[:6] for t in re.findall(r"[a-z0-9]+", text) if t not in STOPWORDS and len(t) > 1]


class BM25:
    def __init__(self, docs, k1=1.4, b=0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = np.array([len(d) for d in docs], dtype=np.float32)
        self.avg = float(self.len.mean()) or 1.0
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query_tokens):
        s = np.zeros(len(self.tf), dtype=np.float32)
        for t in set(query_tokens):
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i, tf in enumerate(self.tf):
                f = tf.get(t)
                if f:
                    s[i] += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
        return s

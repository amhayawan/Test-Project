"""Document types that go through maker-checker approval. Each module registers its own in AppConfig.ready()."""
DOC_TYPES = {}


def register(code, label):
    DOC_TYPES[code] = label


def doc_type_label(code):
    return DOC_TYPES.get(code, code)


def choices():
    return sorted(DOC_TYPES.items(), key=lambda kv: kv[0])

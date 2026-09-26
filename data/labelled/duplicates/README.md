# Duplicate-pair dataset area

Status: `NO PRODUCTION LABELS AVAILABLE`.

The schema and validation code are in
`backend/app/ml/data/duplicate_pairs.py`. Future human annotations must use
the three labels `DUPLICATE`, `NOT_DUPLICATE`, and `UNCERTAIN`, include the
required provenance fields, and preserve `event_id_when_known` or
`incident_id_when_known` where known.

`sample_pairs.json` is explicitly `UNIT_TEST_ONLY`; it is a schema/validation
fixture and is not an approved corpus, training set, validation set, test set,
or quality measurement.

`development_feature_corpus.txt` is also explicitly development-only. It is
unlabeled text used solely to freeze deterministic TF-IDF vocabulary/IDF state
for local tests. It is not a duplicate-pair dataset and does not contain
production labels.

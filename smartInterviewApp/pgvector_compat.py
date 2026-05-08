from __future__ import annotations

from django.db import models

try:
    from pgvector.django import HnswIndex as PgHnswIndex
    from pgvector.django import IvfflatIndex as PgIvfflatIndex
    from pgvector.django import VectorField as PgVectorField

    HAS_PGVECTOR = True

    class VectorField(PgVectorField):
        pass

    class HnswIndex(PgHnswIndex):
        pass

    class IvfflatIndex(PgIvfflatIndex):
        pass

except Exception:  # pragma: no cover - local fallback only
    HAS_PGVECTOR = False

    class VectorField(models.JSONField):
        def __init__(self, *args, dimensions: int | None = None, **kwargs):
            self.dimensions = dimensions
            super().__init__(*args, **kwargs)

        def deconstruct(self):
            name, path, args, kwargs = super().deconstruct()
            if self.dimensions is not None:
                kwargs['dimensions'] = self.dimensions
            return name, 'smartInterviewApp.pgvector_compat.VectorField', args, kwargs

    class HnswIndex(models.Index):
        suffix = 'hnsw'

        def __init__(self, *expressions, m: int | None = None, ef_construction: int | None = None, **kwargs):
            self.m = m
            self.ef_construction = ef_construction
            super().__init__(*expressions, **kwargs)

        def create_sql(self, model, schema_editor, using='', **kwargs):
            return None

    class IvfflatIndex(models.Index):
        suffix = 'ivfflat'

        def __init__(self, *expressions, lists: int | None = None, **kwargs):
            self.lists = lists
            super().__init__(*expressions, **kwargs)

        def create_sql(self, model, schema_editor, using='', **kwargs):
            return None

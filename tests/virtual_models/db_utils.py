from django.db.models import Model


def is_preloaded(model: Model, attribute: str) -> bool:
    return (
        model
        and attribute
        and (
            attribute in model._state.fields_cache
            or (
                hasattr(model, "_prefetched_objects_cache")
                and attribute in model._prefetched_objects_cache
            )
            or (
                attribute not in map(lambda f: f.name, model._meta.fields)
                and attribute not in model._meta.fields_map
                and hasattr(model, attribute)
            )
        )
    )

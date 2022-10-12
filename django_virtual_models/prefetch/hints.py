import functools
from dataclasses import dataclass
from typing import List

from django.conf import settings

from ..exceptions import MissingHintsException
from ..query_capture import QueryCountExceededException, max_query_count


def _block_queries(decorated_func):
    return max_query_count(
        max_queries=0,
        only_count_select=True,
        affected_cls_or_fn_name=decorated_func.__qualname__,
        only_log=not settings.DEBUG,
    )


def _wrap_func_blocking_queries(decorated_func, is_active_fn, extra_args=None):
    if not extra_args:
        extra_args = []

    @functools.wraps(decorated_func)
    def wrapper(*args, **kwargs):
        try:
            if is_active_fn():
                with _block_queries(decorated_func):
                    return decorated_func(*args, *extra_args, **kwargs)
            else:
                return decorated_func(*args, *extra_args, **kwargs)
        except QueryCountExceededException as exc:
            extra_query_stack = exc.extra_queries[0]
            s = extra_query_stack["stack"][0]

            raise MissingHintsException(
                f"Unexpected query happened inside `{decorated_func.__qualname__}`.\n"
                f"*Possible* line: {s.filename}:{s.lineno}\n"
                "Please check if all `hints` are correct, "
                "and update them and the virtual model as needed.\n"
                "Also, if this field is deferred on virtual model, "
                "it needs to be hinted with `hints.Virtual`\n"
                "See more details about the query on the other exception above (in console)."
            ) from exc

    return wrapper


class OnOffDecorator:
    def __init__(self):
        self.is_active = False

    def activate(self):
        self.is_active = True

    def __call__(self, decorated_func):
        wrapper = _wrap_func_blocking_queries(
            decorated_func,
            is_active_fn=lambda: self.is_active,
        )
        wrapper._decorator_instance = self
        return wrapper


class from_types_of(OnOffDecorator):  # noqa: N801
    """
    Decorator factory to fetch types for virtual models performance optimizations.
    """

    def __init__(self, typed_func, obj_param_name):
        super().__init__()
        self.typed_func = typed_func
        self.obj_param_name = obj_param_name

    def __call__(self, decorated_func):
        wrapper = _wrap_func_blocking_queries(
            decorated_func,
            is_active_fn=lambda: self.is_active,
            extra_args=[self.typed_func],
        )
        wrapper._decorator_instance = self
        return wrapper


class from_serializer(OnOffDecorator):  # noqa: N801
    """
    Decorator factory use a serializer fields for virtual models performance optimizations.
    Should decorate a `SerializerMethodField` method that returns a serializer `.data`,
    which only makes sense when nesting serializers declaratively was not possible.
    """

    def __init__(self, serializer_cls, serializer_kwargs=None):
        super().__init__()
        self.serializer_cls = serializer_cls
        self.serializer_kwargs = serializer_kwargs

    def __call__(self, decorated_func):
        if self.serializer_kwargs is not None:
            extra_args = [self.serializer_cls, self.serializer_kwargs]
        else:
            extra_args = [self.serializer_cls]
        wrapper = _wrap_func_blocking_queries(
            decorated_func,
            is_active_fn=lambda: self.is_active,
            extra_args=extra_args,
        )
        wrapper._decorator_instance = self
        return wrapper


class no_deferred_fields(OnOffDecorator):  # noqa: N801
    """
    Decorator factory to mark method field safe since it uses only concrete fields
    already specified at Meta.fields of current Serializer.
    TODO: make this work with @no_deferred_fields, not only @no_deferred_fields()
    """


class defined_on_virtual_model(OnOffDecorator):  # noqa: N801
    """
    Decorator factory to mark method field as defined on virtual model.
    TODO: make this work with @defined_on_virtual_model, not only @defined_on_virtual_model()
    """


@dataclass
class Virtual:
    fields: List[str]

    def __init__(self, *args):
        self.fields = list(args)

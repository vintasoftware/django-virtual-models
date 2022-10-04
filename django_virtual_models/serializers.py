import logging

from django.conf import settings

from rest_framework.serializers import ModelSerializer

from .exceptions import ImproperlyConfiguredVirtualModelSerializer
from .prefetch import serializer_optimization
from .query_capture import max_query_count

logger = logging.getLogger(__name__)


class VirtualModelSerializerMixin:
    raise_exception_on_max_queries = True
    max_queries_count = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # if raise_exception_on_max_queries is set at the view,
        # override the serializer-level one with it:
        view = self.context.get("view")
        if view and hasattr(view, "raise_exception_on_max_queries"):
            self.raise_exception_on_max_queries = view.raise_exception_on_max_queries

        # We can't solve all cases of N+1
        # because updates on DRF can cause N+1s.
        # See: https://github.com/encode/django-rest-framework/pull/8043
        # Check `UpdateModelMixin`, for example.
        # So ignore N+1s when rendering responses in updates:
        request = self.context.get("request")
        self._is_create_or_update_request = request and request.method in {"POST", "PUT", "PATCH"}

    def _has_virtual_model(self):
        return bool(getattr(self.Meta, "virtual_model", False))

    def get_max_queries_count(self):
        return self.max_queries_count

    def to_representation(self, *args, **kwargs):
        if not settings.DEBUG:
            return super().to_representation(*args, **kwargs)
        else:
            if not self._is_create_or_update_request and self.raise_exception_on_max_queries:
                with max_query_count.for_serializer(
                    serializer_instance=self,
                    max_queries=self.get_max_queries_count(),
                ):
                    return super().to_representation(*args, **kwargs)
            else:
                with max_query_count.for_serializer(
                    serializer_instance=self,
                    max_queries=self.get_max_queries_count(),
                    only_log=True,
                ):
                    result = super().to_representation(*args, **kwargs)
                return result

    def get_request_user(self):
        request = self.context.get("request")
        if request and not request.user.is_anonymous:
            return request.user

    def get_optimized_queryset(self, initial_queryset):
        cls_name = self.__class__.__name__
        if not self._has_virtual_model():
            raise ImproperlyConfiguredVirtualModelSerializer(
                f"{cls_name} is missing a virtual_model attribute inside `class Meta:`"
            )

        virtual_model = self.Meta.virtual_model
        logger.debug(
            "Using virtual models on %(cls_name)s. Finding lookup_list...",
            {"cls_name": cls_name},
        )
        virtual_model_instance = virtual_model(user=self.get_request_user())
        lookup_list = serializer_optimization.LookupFinder(
            serializer_instance=self,
            virtual_model=virtual_model_instance,
            block_queries=self.raise_exception_on_max_queries,
        ).recursively_find_lookup_list()
        logger.debug(
            "Using virtual models on %(cls_name)s. Found lookup_list: %(lookup_list)s",
            {"cls_name": cls_name, "lookup_list": lookup_list},
        )
        return virtual_model_instance.get_optimized_queryset(
            qs=initial_queryset, lookup_list=lookup_list
        )


class VirtualModelSerializer(VirtualModelSerializerMixin, ModelSerializer):
    pass

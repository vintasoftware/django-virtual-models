from rest_framework import generics


class GenericVirtualModelViewMixin:
    def _get_empty_serializer(self):
        serializer_class = self.get_serializer_class()
        kwargs = {"context": self.get_serializer_context()}
        return serializer_class(instance=None, **kwargs)

    def get_queryset(self):
        """
        Get the list of items for this view.
        This must be an iterable, and may be a queryset.
        Defaults to using `self.queryset`.

        This method should always be used rather than accessing `self.queryset`
        directly, as `self.queryset` gets evaluated only once, and those results
        are cached for all subsequent requests.

        You may want to override this if you need to provide different
        querysets depending on the incoming request.

        (Eg. return a list of items that is specific to the user)
        """
        queryset = super().get_queryset()
        serializer_instance = self._get_empty_serializer()
        optimized_queryset = serializer_instance.get_optimized_queryset(queryset)
        return optimized_queryset


class VirtualModelListAPIView(GenericVirtualModelViewMixin, generics.ListAPIView):
    """
    Copy of django-rest-framework's `ListAPIView`
    but with changes to call the method `get_optimized_queryset`
    from the associated `VirtualModelSerializer`.
    This ensures the queryset used by the serializer will
    contain all annotations, joins, and prefetches needed.
    """


class VirtualModelRetrieveAPIView(GenericVirtualModelViewMixin, generics.RetrieveAPIView):
    """
    Copy of django-rest-framework's `RetrieveAPIView`
    but with changes to call the method `get_optimized_queryset`
    from the associated `VirtualModelSerializer`.
    This ensures the queryset used by the serializer will
    contain all annotations, joins, and prefetches needed.
    """

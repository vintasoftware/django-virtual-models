from unittest.mock import MagicMock

from django.test import TestCase

from rest_framework import serializers

from model_bakery import baker

import django_virtual_models as v

from ..virtual_models.models import Course, User


class VirtualModelSerializerTest(TestCase):
    def test_pass_serializer_context_to_virtual_model(self):
        class MockedVirtualCourse(v.VirtualModel):
            something = v.Annotation(
                lambda qs, user, **kwargs: qs.annotate_something(user=user, **kwargs)
            )

            class Meta:
                model = Course
                deferred_fields = ["name", "description", "something"]

        class CourseSerializer(v.VirtualModelSerializer):
            something = serializers.CharField()

            class Meta:
                model = Course
                virtual_model = MockedVirtualCourse
                fields = ["name", "description", "something"]

        user = baker.make(User)
        user.is_anonymous = False
        request = MagicMock()
        request.method = "GET"
        request.user = user
        serializer_context = {"request": request, "value": 12345}
        mock_qs = MagicMock()
        virtual_course_serializer = CourseSerializer(instance=None, context=serializer_context)
        virtual_course_serializer.get_optimized_queryset(mock_qs)

        mock_qs.annotate_something.assert_called_once_with(
            user=user, serializer_context=serializer_context
        )

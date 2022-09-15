from django.db.models import F
from django.db.models.functions import Substr
from django.test import TestCase

import django_virtual_models as v
from django_virtual_models.exceptions import (
    InvalidFieldException,
    InvalidLookupException,
    InvalidVirtualModelParams,
)

from .models import Assignment, Course, Lesson


class NestedLessons(v.VirtualModel):
    small_content = v.Expression(Substr("content", 1, 300))


class VirtualCourse(v.VirtualModel):
    small_description = v.Expression(Substr("description", 1, 128))
    lessons = NestedLessons(manager=Lesson.objects)

    class Meta:
        model = Course
        deferred_fields = ["description"]


class VirtualModelsExceptionTest(TestCase):
    def setUp(self):
        super().setUp()

        # full lookup list based on VirtualCourse
        self.lookup_list = [
            "small_description",
        ]

    def test_lookup_not_declared_in_virtual_model(self):
        virtual_course = VirtualCourse()
        qs = Course.objects.all()
        lookup_list = self.lookup_list + ["created_by"]

        with self.assertRaises(InvalidLookupException) as ctx:
            virtual_course.get_optimized_queryset(qs=qs, lookup_list=lookup_list)

        assert "created_by" in str(ctx.exception)

    def test_lookup_not_supported_by_nested_join(self):
        class SimpleVirtualLesson(v.VirtualModel):
            course = v.NestedJoin(model_cls=Course)

            class Meta:
                model = Lesson

        virtual_lesson = SimpleVirtualLesson()
        qs = Lesson.objects.all()
        lookup_list = ["course__wrong_created_by"]

        with self.assertRaises(InvalidLookupException) as ctx:
            virtual_lesson.get_optimized_queryset(qs=qs, lookup_list=lookup_list)

        assert "wrong_created_by" in str(ctx.exception)

    def test_lookup_not_declared_in_nested_virtual_model(self):
        virtual_course = VirtualCourse()
        qs = Course.objects.all()
        lookup_list = self.lookup_list + ["lessons__course"]

        with self.assertRaises(InvalidLookupException) as ctx:
            virtual_course.get_optimized_queryset(qs=qs, lookup_list=lookup_list)

        assert "course" in str(ctx.exception)

    def test_block_double_underscore(self):
        with self.assertRaises(InvalidFieldException) as ctx:

            class BadVirtualCourse(VirtualCourse):  # noqa  # pylint: disable=unused-variable
                created_by__email = v.Expression(F("created_by__email"))

        assert "shouldn't cointain `__`" in str(ctx.exception)

    def test_block_bad_to_attr(self):
        with self.assertRaises(InvalidVirtualModelParams) as ctx:

            class BadVirtualCourse(VirtualCourse):  # noqa  # pylint: disable=unused-variable
                user_assignment = v.VirtualModel(
                    manager=Assignment.objects, lookup="assignments", to_attr=None
                )

        assert "provide `lookup` and `to_attr` together" in str(ctx.exception)

    def test_block_virtual_model_without_meta_model(self):
        with self.assertRaises(InvalidVirtualModelParams) as ctx:

            class BadVirtualCourse1(v.VirtualModel):
                small_description = v.Expression(Substr("description", 1, 128))

            BadVirtualCourse1()

        assert "Always provide a `manager` or `Meta.model" in str(ctx.exception)

        with self.assertRaises(InvalidVirtualModelParams) as ctx:

            class BadVirtualCourse2(v.VirtualModel):
                small_description = v.Expression(Substr("description", 1, 128))

                class Meta:
                    pass

            BadVirtualCourse2()

        assert "Always provide a `manager` or `Meta.model" in str(ctx.exception)

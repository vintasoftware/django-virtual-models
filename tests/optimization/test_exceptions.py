from django.test import TestCase

from rest_framework import serializers

from typing_extensions import Annotated

import django_virtual_models as v
from django_virtual_models.prefetch import hints
from django_virtual_models.prefetch.exceptions import (
    ImproperlyAnnotatedCodeException,
    MissingVirtualModelFieldException,
)
from django_virtual_models.prefetch.serializer_optimization import LookupFinder

from ..virtual_models.models import CompletedLesson, Course, Lesson, User


class VirtualCourse(v.VirtualModel):
    lessons = v.VirtualModel(manager=Lesson.objects)

    class Meta:
        model = Course


def get_lesson_title_list(course: Annotated[Course, hints.Virtual("lessons")]):
    ...


class BaseCourseSerializer(serializers.ModelSerializer):
    lesson_titles_from_method = serializers.SerializerMethodField()
    lesson_titles_from_function = serializers.SerializerMethodField()

    class Meta:
        model = Course
        virtual_model = VirtualCourse
        fields = [
            "lesson_titles_from_method",
            "lesson_titles_from_function",
        ]

    def get_lesson_titles_from_method(self, course: Annotated[Course, hints.Virtual("lessons")]):
        ...

    @v.hints.from_types_of(get_lesson_title_list, "course")
    def get_lesson_titles_from_function(self, course, get_lesson_title_list_helper):
        ...


class LookupFinderExceptionTest(TestCase):
    def test_method_without_type_annotation_raises_exception(self):
        class BrokenCourseSerializer(BaseCourseSerializer):
            def get_lesson_titles_from_method(self, course):  # no type annotation here
                ...

        qs = Course.objects.all()
        serializer_instance = BrokenCourseSerializer(instance=qs, many=True)
        virtual_model = VirtualCourse()

        with self.assertRaises(ImproperlyAnnotatedCodeException) as ctx:
            LookupFinder(
                serializer_instance=serializer_instance, virtual_model=virtual_model
            ).recursively_find_lookup_list()

        assert (
            "`get_lesson_titles_from_method` inside `BrokenCourseSerializer` "
            "must have a `hints` decorator or a single `Annotated` type hint "
            "with a single `hints.Virtual` inside it." in str(ctx.exception)
        )

    def test_method_without_annotated_raises_exception(self):
        class BrokenCourseSerializer(BaseCourseSerializer):
            def get_lesson_titles_from_method(self, course: Course):  # no Annotated here
                ...

        qs = Course.objects.all()
        serializer_instance = BrokenCourseSerializer(instance=qs, many=True)
        virtual_model = VirtualCourse()

        with self.assertRaises(ImproperlyAnnotatedCodeException) as ctx:
            LookupFinder(
                serializer_instance=serializer_instance, virtual_model=virtual_model
            ).recursively_find_lookup_list()

        assert (
            "`get_lesson_titles_from_method` inside `BrokenCourseSerializer` "
            "must have a single `Annotated` type hint with a single `hints.Virtual` inside it."
            in str(ctx.exception)
        )

    def test_method_with_wrong_annotated_raises_exception(self):
        class BrokenCourseSerializer(BaseCourseSerializer):
            def get_lesson_titles_from_method(
                self, course: Annotated[Course, ()]  # wrong Annotated here
            ):
                ...

        qs = Course.objects.all()
        serializer_instance = BrokenCourseSerializer(instance=qs, many=True)
        virtual_model = VirtualCourse()

        with self.assertRaises(ImproperlyAnnotatedCodeException) as ctx:
            LookupFinder(
                serializer_instance=serializer_instance, virtual_model=virtual_model
            ).recursively_find_lookup_list()

        assert (
            "`get_lesson_titles_from_method` inside `BrokenCourseSerializer` "
            "must have a single `Annotated` type hint with a single `hints.Virtual` inside it."
            in str(ctx.exception)
        )

    def test_method_with_multiple_annotated_raises_exception(self):
        class BrokenCourseSerializer(BaseCourseSerializer):
            def get_lesson_titles_from_method(
                self,
                course: Annotated[Course, ()],
                something_else: Annotated[object, ()] = None,  # two Annotated
            ):
                ...

        qs = Course.objects.all()
        serializer_instance = BrokenCourseSerializer(instance=qs, many=True)
        virtual_model = VirtualCourse()

        with self.assertRaises(ImproperlyAnnotatedCodeException) as ctx:
            LookupFinder(
                serializer_instance=serializer_instance, virtual_model=virtual_model
            ).recursively_find_lookup_list()

        assert (
            "`get_lesson_titles_from_method` inside `BrokenCourseSerializer` has "
            "more than 1 type annotated parameter. It should have a single one. Please change it."
            in str(ctx.exception)
        )

    def test_method_with_two_prefetch_annotations_raises_exception(self):
        class BrokenCourseSerializer(BaseCourseSerializer):
            def get_lesson_titles_from_method(
                self,
                course: Annotated[
                    Course,
                    hints.Virtual("lessons"),
                    hints.Virtual("settings")
                    # two prefetch here
                ],
            ):
                ...

        qs = Course.objects.all()
        serializer_instance = BrokenCourseSerializer(instance=qs, many=True)
        virtual_model = VirtualCourse()

        with self.assertRaises(ImproperlyAnnotatedCodeException) as ctx:
            LookupFinder(
                serializer_instance=serializer_instance, virtual_model=virtual_model
            ).recursively_find_lookup_list()

        assert (
            "`get_lesson_titles_from_method` inside `BrokenCourseSerializer` "
            "must have a single `Annotated` type hint with a single `hints.Virtual` inside it."
            in str(ctx.exception)
        )

    def test_function_without_type_annotation_raises_exception(self):
        def get_lesson_title_list(course):  # no type annotation here
            ...

        class BrokenCourseSerializer(BaseCourseSerializer):
            @v.hints.from_types_of(get_lesson_title_list, "course")
            def get_lesson_titles_from_function(self, course, get_lesson_title_list_helper):
                ...

        qs = Course.objects.all()
        serializer_instance = BrokenCourseSerializer(instance=qs, many=True)
        virtual_model = VirtualCourse()

        with self.assertRaises(ImproperlyAnnotatedCodeException) as ctx:
            LookupFinder(
                serializer_instance=serializer_instance, virtual_model=virtual_model
            ).recursively_find_lookup_list()

        assert "Couldn't find the annotated param `course` on function " in str(ctx.exception)
        assert "get_lesson_title_list" in str(ctx.exception)
        assert (
            "referenced by decorator `from_types_of` on "
            "`get_lesson_titles_from_function` inside `BrokenCourseSerializer`"
            in str(ctx.exception)
        )

    def test_function_with_wrong_param_name_raises_exception(self):
        class BrokenCourseSerializer(BaseCourseSerializer):
            @v.hints.from_types_of(
                get_lesson_title_list, obj_param_name="course_blabla"  # wrong param name
            )
            def get_lesson_titles_from_function(self, course, get_lesson_title_list_helper):
                ...

        qs = Course.objects.all()
        serializer_instance = BrokenCourseSerializer(instance=qs, many=True)
        virtual_model = VirtualCourse()

        with self.assertRaises(ImproperlyAnnotatedCodeException) as ctx:
            LookupFinder(
                serializer_instance=serializer_instance, virtual_model=virtual_model
            ).recursively_find_lookup_list()

        assert "Couldn't find the annotated param `course_blabla` on function " in str(
            ctx.exception
        )
        assert "get_lesson_title_list" in str(ctx.exception)
        assert (
            "Please fix decorator `from_types_of` on "
            "`get_lesson_titles_from_function` inside `BrokenCourseSerializer`"
            in str(ctx.exception)
        )

    def test_function_without_annotated_raises_exception(self):
        def get_lesson_title_list(course: Course):  # no Annotated here
            ...

        class BrokenCourseSerializer(BaseCourseSerializer):
            @v.hints.from_types_of(get_lesson_title_list, "course")
            def get_lesson_titles_from_function(self, course, get_lesson_title_list_helper):
                ...

        qs = Course.objects.all()
        serializer_instance = BrokenCourseSerializer(instance=qs, many=True)
        virtual_model = VirtualCourse()

        with self.assertRaises(ImproperlyAnnotatedCodeException) as ctx:
            LookupFinder(
                serializer_instance=serializer_instance, virtual_model=virtual_model
            ).recursively_find_lookup_list()

        assert "get_lesson_title_list" in str(ctx.exception)
        assert (
            "referenced by decorator `from_types_of` on `get_lesson_titles_from_function` "
            "inside `BrokenCourseSerializer` must have a `Annotated` type hint on param `course` "
            "with a single `hints.Virtual` inside it." in str(ctx.exception)
        )

    def test_function_with_wrong_annotated_raises_exception(self):
        def get_lesson_title_list(course: Annotated[Course, ()]):  # wrong Annotated here
            ...

        class BrokenCourseSerializer(BaseCourseSerializer):
            @v.hints.from_types_of(get_lesson_title_list, "course")
            def get_lesson_titles_from_function(self, course, get_lesson_title_list_helper):
                ...

        qs = Course.objects.all()
        serializer_instance = BrokenCourseSerializer(instance=qs, many=True)
        virtual_model = VirtualCourse()

        with self.assertRaises(ImproperlyAnnotatedCodeException) as ctx:
            LookupFinder(
                serializer_instance=serializer_instance, virtual_model=virtual_model
            ).recursively_find_lookup_list()

        assert "get_lesson_title_list" in str(ctx.exception)
        assert (
            "referenced by decorator `from_types_of` on `get_lesson_titles_from_function` "
            "inside `BrokenCourseSerializer` must have a `Annotated` type hint on param `course` "
            "with a single `hints.Virtual` inside it." in str(ctx.exception)
        )

    def test_function_with_two_prefetch_annotations_raises_exception(self):
        def get_lesson_title_list(
            course: Annotated[
                Course,
                hints.Virtual("lessons"),
                hints.Virtual("settings")
                # two prefetch here
            ]
        ):
            ...

        class BrokenCourseSerializer(BaseCourseSerializer):
            @v.hints.from_types_of(get_lesson_title_list, "course")
            def get_lesson_titles_from_function(self, course, get_lesson_title_list_helper):
                ...

        qs = Course.objects.all()
        serializer_instance = BrokenCourseSerializer(instance=qs, many=True)
        virtual_model = VirtualCourse()

        with self.assertRaises(ImproperlyAnnotatedCodeException) as ctx:
            LookupFinder(
                serializer_instance=serializer_instance, virtual_model=virtual_model
            ).recursively_find_lookup_list()

        assert "get_lesson_title_list" in str(ctx.exception)
        assert (
            "referenced by decorator `from_types_of` on `get_lesson_titles_from_function` "
            "inside `BrokenCourseSerializer` must have a `Annotated` type hint on param `course` "
            "with a single `hints.Virtual` inside it." in str(ctx.exception)
        )

    def test_deeply_nested_serializer_with_join_raises_exception(self):
        class CreatorSerializer(serializers.ModelSerializer):
            class Meta:
                model = User
                fields = ["email"]

        class CourseCreatorSerializer(serializers.ModelSerializer):
            created_by = CreatorSerializer()

            class Meta:
                model = Course
                fields = ["created_by"]

        class LessonSerializer(serializers.ModelSerializer):
            course = CourseCreatorSerializer()

            class Meta:
                model = Lesson
                fields = ["course"]

        class CompletedLessonSerializer(serializers.ModelSerializer):
            lesson = LessonSerializer()

            class Meta:
                model = CompletedLesson
                fields = ["lesson"]

        class SimpleVirtualCompletedLesson(v.VirtualModel):
            lesson = v.NestedJoin(model_cls=Lesson)

            class Meta:
                model = CompletedLesson

        qs = CompletedLesson.objects.all()
        serializer_instance = CompletedLessonSerializer(instance=qs, many=True)
        virtual_model = SimpleVirtualCompletedLesson()

        with self.assertRaises(MissingVirtualModelFieldException) as ctx:
            LookupFinder(
                serializer_instance=serializer_instance, virtual_model=virtual_model
            ).recursively_find_lookup_list()

        assert (
            "Cannot use a `NestedJoin` for `lesson` inside `SimpleVirtualCompletedLesson`. "
            "`course` must be a field of `lesson`, because it's a nested serializer on `LessonSerializer`. "
            "Change from `NestedJoin` to a `VirtualModel` and add `course` as a field."
            in str(ctx.exception)
        )

    def test_nested_serializer_without_nested_virtual_model_raises_exception(self):
        class LessonSerializer(serializers.ModelSerializer):
            class Meta:
                model = Lesson
                fields = ["title"]

        class CompletedLessonSerializer(serializers.ModelSerializer):
            lesson = LessonSerializer()

            class Meta:
                model = CompletedLesson
                fields = ["lesson"]

        class SimpleVirtualCompletedLesson(v.VirtualModel):
            class Meta:
                model = CompletedLesson

        qs = CompletedLesson.objects.all()
        serializer_instance = CompletedLessonSerializer(instance=qs, many=True)
        virtual_model = SimpleVirtualCompletedLesson()

        with self.assertRaises(MissingVirtualModelFieldException) as ctx:
            LookupFinder(
                serializer_instance=serializer_instance, virtual_model=virtual_model
            ).recursively_find_lookup_list()

        assert (
            "`lesson` must be defined in `SimpleVirtualCompletedLesson` "
            "because it's a nested serializer on `CompletedLessonSerializer`" in str(ctx.exception)
        )

    def test_prefetch_required_on_property_raises_exception(self):
        class BrokenCourseSerializer(serializers.ModelSerializer):
            description_first_line = serializers.SerializerMethodField()

            class Meta:
                model = Course
                fields = ["description_first_line"]

            def get_description_first_line(
                self,
                course: Annotated[
                    Course,
                    hints.Virtual("description_first_line"),  # prefetch required on property
                ],
            ):
                ...

        qs = Course.objects.all()
        serializer_instance = BrokenCourseSerializer(instance=qs, many=True)
        virtual_model = VirtualCourse()

        with self.assertRaises(MissingVirtualModelFieldException) as ctx:
            LookupFinder(
                serializer_instance=serializer_instance, virtual_model=virtual_model
            ).recursively_find_lookup_list()

        assert (
            "Property field `description_first_line` hinted at `get_description_first_line` "
            "in `BrokenCourseSerializer` must be defined in `VirtualCourse` "
            "(or switched for a concrete field)" in str(ctx.exception)
        )

    def test_prefetch_required_on_non_concrete_field_raises_exception(self):
        class BrokenCourseSerializer(serializers.ModelSerializer):
            foo = serializers.SerializerMethodField()

            class Meta:
                model = Course
                fields = ["foo"]

            def get_foo(
                self,
                course: Annotated[
                    Course,
                    hints.Virtual("foo"),  # prefetch required on non-concrete field
                ],
            ):
                ...

        qs = Course.objects.all()
        serializer_instance = BrokenCourseSerializer(instance=qs, many=True)
        virtual_model = VirtualCourse()

        with self.assertRaises(MissingVirtualModelFieldException) as ctx:
            LookupFinder(
                serializer_instance=serializer_instance, virtual_model=virtual_model
            ).recursively_find_lookup_list()

        assert (
            "Non-concrete field `foo` hinted at `get_foo` "
            "in `BrokenCourseSerializer` must be defined in `VirtualCourse`" in str(ctx.exception)
        )

    def test_url_field_raises_exception(self):
        class BrokenCourseSerializer(serializers.HyperlinkedModelSerializer):
            class Meta:
                model = Course
                fields = ["url"]

        qs = Course.objects.all()
        serializer_instance = BrokenCourseSerializer(instance=qs, many=True)
        virtual_model = VirtualCourse()

        with self.assertRaises(ImproperlyAnnotatedCodeException) as ctx:
            LookupFinder(
                serializer_instance=serializer_instance, virtual_model=virtual_model
            ).recursively_find_lookup_list()

        assert (
            "`url` inside `BrokenCourseSerializer` is a `HyperlinkedIdentityField` "
            "that django-virtual-models cannot handle yet. "
            "Please replace it with a `SerializerMethodField`." in str(ctx.exception)
        )

    def test_annotated_field_not_in_virtual_model_raises_exception(self):
        class BrokenCourseSerializer(serializers.ModelSerializer):
            annotated_field = serializers.CharField(read_only=True)

            class Meta:
                model = Course
                fields = ["annotated_field"]

        qs = Course.objects.all()
        serializer_instance = BrokenCourseSerializer(instance=qs, many=True)
        virtual_model = VirtualCourse()

        with self.assertRaises(MissingVirtualModelFieldException) as ctx:
            LookupFinder(
                serializer_instance=serializer_instance, virtual_model=virtual_model
            ).recursively_find_lookup_list()

        assert (
            "`annotated_field` used by `BrokenCourseSerializer` must be defined in `VirtualCourse`"
            in str(ctx.exception)
        )

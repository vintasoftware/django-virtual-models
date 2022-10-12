import os

from django.db.models import F
from django.template.defaultfilters import slugify
from django.test import TestCase, override_settings

from rest_framework import serializers

import pytest
from model_bakery import baker
from typing_extensions import Annotated

import django_virtual_models as v
from django_virtual_models.exceptions import MissingHintsException
from django_virtual_models.prefetch import hints
from django_virtual_models.prefetch.serializer_optimization import LookupFinder

from ..virtual_models.models import (
    Assignment,
    CompletedLesson,
    Course,
    Facilitator,
    Lesson,
    SQArrayAgg,
    User,
)


class NestedAssignment(v.VirtualModel):
    email = v.Expression(F("user__email"))
    course = v.VirtualModel(manager=Course.objects)
    lessons_total = v.Annotation(lambda qs, **kwargs: qs.annotate_lessons_total())
    lessons_completed_total = v.Annotation(
        lambda qs, **kwargs: qs.annotate_lessons_completed_total()
    )
    completed_lessons = v.VirtualModel(manager=Lesson.objects)


class NestedUserAssignment(NestedAssignment):
    def get_prefetch_queryset(self, user=None, **kwargs):
        if user is None:
            return Assignment.objects.none()
        return Assignment.objects.filter(user=user)


class VirtualCourse(v.VirtualModel):
    created_by = v.NestedJoin(model_cls=User)
    facilitator_emails = v.Expression(SQArrayAgg(F("facilitators__email")))
    user_assignment = NestedUserAssignment(
        manager=Assignment.objects, lookup="assignments", to_attr="user_assignment"
    )
    assignments = NestedAssignment(
        manager=Assignment.objects,
    )
    lessons = v.VirtualModel(manager=Lesson.objects)
    settings = v.NoOp()

    class Meta:
        model = Course
        deferred_fields = ["description"]


class NestedAssignmentSerializer(serializers.ModelSerializer):
    email = serializers.EmailField()
    lessons_total = serializers.IntegerField()
    lessons_completed_total = serializers.IntegerField()

    class Meta:
        model = Assignment
        fields = [
            "email",
            "lessons_total",
            "lessons_completed_total",
        ]


class NestedUserAssignmentSerializer(NestedAssignmentSerializer):
    class Meta(NestedAssignmentSerializer.Meta):
        fields = NestedAssignmentSerializer.Meta.fields + [
            "last_completed_lesson_name",  # property
        ]


def get_lesson_title_list(course: Annotated[Course, hints.Virtual("lessons")]):
    lessons = list(course.lessons.all())
    lessons.sort(key=lambda lesson: lesson.created)
    return [lesson.title for lesson in lessons]


class CourseSerializer(serializers.ModelSerializer):
    slug = serializers.SerializerMethodField()
    creator_id = serializers.PrimaryKeyRelatedField(source="created_by", read_only=True)
    creator_email = serializers.EmailField(source="created_by.email")
    facilitator_emails = serializers.SerializerMethodField()
    facilitator_domains = serializers.SerializerMethodField()
    user_assignment = serializers.SerializerMethodField()
    assignments = NestedAssignmentSerializer(many=True)
    lesson_ids = serializers.PrimaryKeyRelatedField(source="lessons", read_only=True, many=True)
    lesson_titles = serializers.SerializerMethodField()

    class Meta:
        model = Course
        virtual_model = VirtualCourse
        fields = [
            "name",
            "name_title_case",  # method
            "slug",
            "creator_id",
            "creator_email",
            "description_first_line",  # property
            "facilitator_emails",
            "facilitator_domains",
            "user_assignment",
            "assignments",
            "lesson_ids",
            "lesson_titles",
        ]

    @hints.no_deferred_fields()
    def get_slug(self, course):
        # use only concrete fields below
        return slugify(course.name)

    @hints.defined_on_virtual_model()
    def get_facilitator_emails(self, course):
        if hasattr(course, "facilitator_emails"):
            return course.facilitator_emails

        # this won't run because it's defined on virtual model,
        # but one could add fallback code here:
        return None

    def get_facilitator_domains(
        self, course: Annotated[Course, hints.Virtual("facilitator_emails")]
    ):
        if hasattr(course, "facilitator_emails"):
            return list({email.split("@")[-1] for email in course.facilitator_emails})

        # this won't run because it's defined on virtual model,
        # but one could add fallback code here:
        return None

    @hints.from_serializer(NestedUserAssignmentSerializer)
    def get_user_assignment(self, obj, serializer_cls):
        if getattr(obj, "user_assignment", None):
            return serializer_cls(obj.user_assignment[0]).data
        return None

    @v.hints.from_types_of(get_lesson_title_list, "course")
    def get_lesson_titles(self, course, get_lesson_title_list_helper):
        return get_lesson_title_list_helper(course)


class LookupFinderTests(TestCase):
    def setUp(self):
        super().setUp()
        self.user = baker.make(User)

        # test data creation
        self.courses = baker.make(Course, _fill_optional=True, _quantity=3)
        self.course_to_related = {}
        for course in self.courses:
            lessons = baker.make(Lesson, course=course, _fill_optional=True, _quantity=3)
            facilitators = baker.make(Facilitator, course=course, _fill_optional=True, _quantity=3)
            # self.user assignment
            user_assignment = baker.make(Assignment, user=self.user, course=course)
            assignments = [user_assignment]
            # other users assignments
            assignments += baker.make(Assignment, course=course, _fill_optional=True, _quantity=3)

            self.course_to_related[course] = {
                "lessons": lessons,
                "facilitators": facilitators,
                "user_assignment": user_assignment,
                "assignments": assignments,
            }

        # complete all lessons minus 1 for self.user on the first course
        first_course_related = self.course_to_related[self.courses[0]]
        lessons_from_first_course = first_course_related["lessons"]
        user_assignment_on_first_course = first_course_related["user_assignment"]
        self.user_completed_lessons_on_first_course = [
            baker.make(
                CompletedLesson,
                assignment=user_assignment_on_first_course,
                lesson=lesson,
                _fill_optional=True,
            )
            for lesson in lessons_from_first_course[:-1]
        ]

    def test_found_lookup_list(self):
        qs = Course.objects.all()
        serializer_instance = CourseSerializer(instance=qs, context={"user": self.user}, many=True)
        virtual_course = VirtualCourse()

        lookup_list = LookupFinder(
            serializer_instance=serializer_instance, virtual_model=virtual_course
        ).recursively_find_lookup_list()

        assert sorted(lookup_list) == sorted(
            [
                "assignments",
                "assignments__email",
                "assignments__lessons_completed_total",
                "assignments__lessons_total",
                "created_by",
                "created_by__email",
                "facilitator_emails",
                "lessons",
                "name",
                "description",
                "user_assignment",
                "user_assignment__completed_lessons",
                "user_assignment__course",
                "user_assignment__email",
                "user_assignment__lessons_completed_total",
                "user_assignment__lessons_total",
            ]
        )

    def test_found_lookup_list_has_no_n_plus_one_queries(self):
        qs = Course.objects.all()
        serializer_instance = CourseSerializer(instance=qs, context={"user": self.user}, many=True)
        virtual_course = VirtualCourse()

        lookup_list = LookupFinder(
            serializer_instance=serializer_instance, virtual_model=virtual_course
        ).recursively_find_lookup_list()

        optimized_qs = virtual_course.get_optimized_queryset(qs=qs, lookup_list=lookup_list)
        with self.assertNumQueries(3):
            course_list = list(optimized_qs)
            assert len(course_list) == 3

    def test_ignored_nested_serializer_with_noop(self):
        """
        Sometimes one needs a nested serializer generated dynamically.
        These can be ignored with `v.NoOp`. Therefore, test if `v.NoOp` ignores a nested serializer.
        """

        class SettingsSerializer(serializers.Serializer):
            default = serializers.CharField()

        class CourseSerializerWithSettings(CourseSerializer):
            settings = SettingsSerializer()

            class Meta(CourseSerializer.Meta):
                fields = ["settings"]

        qs = Course.objects.all()
        serializer_instance = CourseSerializerWithSettings(
            instance=qs, context={"user": self.user}, many=True
        )
        virtual_course = VirtualCourse()

        # run to see if no exception happens
        lookup_list = LookupFinder(
            serializer_instance=serializer_instance, virtual_model=virtual_course
        ).recursively_find_lookup_list()

        assert "settings" in lookup_list

    def test_from_serializer_hint(self):
        # Override CourseSerializer and replace nested serializers with
        # `SerializerMethodField`s and use `hints.from_serializer` on those.
        class AltCourseSerializer(CourseSerializer):
            user_assignment = serializers.SerializerMethodField()
            assignments = serializers.SerializerMethodField()

            @hints.from_serializer(
                serializer_cls=NestedUserAssignmentSerializer,
                serializer_kwargs={"context": {"foo": "bar"}},
            )
            def get_user_assignment(self, obj, serializer_cls, serializer_kwargs):
                ...

            @hints.from_serializer(serializer_cls=NestedAssignmentSerializer)
            def get_assignments(self, obj, serializer_cls):
                ...

        qs = Course.objects.all()
        serializer_instance = AltCourseSerializer(
            instance=qs, context={"user": self.user}, many=True
        )
        virtual_course = VirtualCourse()

        lookup_list = LookupFinder(
            serializer_instance=serializer_instance, virtual_model=virtual_course
        ).recursively_find_lookup_list()

        assert sorted(lookup_list) == sorted(
            [
                "name",
                "description",
                "created_by",
                "created_by__email",
                "facilitator_emails",
                "user_assignment",
                "user_assignment__email",
                "user_assignment__lessons_total",
                "user_assignment__lessons_completed_total",
                "user_assignment__course",
                "user_assignment__completed_lessons",
                "assignments",
                "assignments__email",
                "assignments__lessons_total",
                "assignments__lessons_completed_total",
                "lessons",
            ]
        )

    def test_nested_serializer_with_join(self):
        """
        1-level nesting like this test works with `NestedJoin`, but 2-levels fails.
        See: `test_deeply_nested_serializer_with_join_raises_exception`
        """

        class CreatorSerializer(serializers.ModelSerializer):
            class Meta:
                model = User
                fields = ["email"]

        class CourseCreatorSerializer(serializers.ModelSerializer):
            created_by = CreatorSerializer()

            class Meta:
                model = Course
                fields = ["created_by"]

        qs = Course.objects.all()
        serializer_instance = CourseCreatorSerializer(
            instance=qs, context={"user": self.user}, many=True
        )
        virtual_course = VirtualCourse()

        lookup_list = LookupFinder(
            serializer_instance=serializer_instance, virtual_model=virtual_course
        ).recursively_find_lookup_list()

        assert sorted(lookup_list) == sorted(["created_by", "created_by__email"])

    @override_settings(DEBUG=True)
    def test_prefetch_hints_block_queries_on_serializer_evaluation(self):
        class BrokenCourseSerializer(CourseSerializer):
            @v.hints.from_types_of(get_lesson_title_list, "course")
            def get_lesson_titles(self, course, get_lesson_title_list_helper):
                list(course.lessons.order_by("title"))  # new query

        qs = Course.objects.all()
        serializer_instance = BrokenCourseSerializer(instance=qs, many=True)
        virtual_model = VirtualCourse()

        lookup_list = LookupFinder(
            serializer_instance=serializer_instance,
            virtual_model=virtual_model,
        ).recursively_find_lookup_list()
        optimized_qs = virtual_model.get_optimized_queryset(qs=qs, lookup_list=lookup_list)
        with self.assertRaises(MissingHintsException) as ctx:
            BrokenCourseSerializer(optimized_qs, many=True).data

        assert "Unexpected query happened inside" in str(ctx.exception)
        assert "BrokenCourseSerializer.get_lesson_titles" in str(ctx.exception)
        assert os.path.basename(__file__) in str(ctx.exception)

    @override_settings(DEBUG=True)
    def test_prefetch_hints_does_not_block_queries_if_false(self):
        class BrokenCourseSerializer(CourseSerializer):
            @v.hints.from_types_of(get_lesson_title_list, "course")
            def get_lesson_titles(self, course, get_lesson_title_list_helper):
                list(course.lessons.order_by("title"))  # new query

        qs = Course.objects.all()
        serializer_instance = BrokenCourseSerializer(instance=qs, many=True)
        virtual_model = VirtualCourse()

        lookup_list = LookupFinder(
            serializer_instance=serializer_instance,
            virtual_model=virtual_model,
            block_queries=False,
        ).recursively_find_lookup_list()
        optimized_qs = virtual_model.get_optimized_queryset(qs=qs, lookup_list=lookup_list)
        with self.assertNumQueries(6):
            BrokenCourseSerializer(optimized_qs, many=True).data

    @override_settings(DEBUG=True)
    @pytest.mark.skip(reason="Not supported yet")
    def test_annotated_blocks_queries_on_serializer_evaluation(self):
        class BrokenCourseSerializer(serializers.ModelSerializer):
            created_by_email = serializers.SerializerMethodField()

            class Meta:
                model = Course
                virtual_model = VirtualCourse
                fields = ["created_by_email"]

            def get_created_by_email(
                self,
                # should have Annotated[Course, hints.Virtual("created_by")]:
                course: Annotated[Course, hints.Virtual("description")],
            ):
                return course.created_by.email

        qs = Course.objects.all()
        serializer_instance = BrokenCourseSerializer(instance=qs, many=True)
        virtual_model = VirtualCourse()

        lookup_list = LookupFinder(
            serializer_instance=serializer_instance,
            virtual_model=virtual_model,
        ).recursively_find_lookup_list()
        optimized_qs = virtual_model.get_optimized_queryset(qs=qs, lookup_list=lookup_list)
        ls = list(optimized_qs)
        with self.assertRaises(MissingHintsException) as ctx:
            BrokenCourseSerializer(ls, many=True).data

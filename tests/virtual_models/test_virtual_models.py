from datetime import datetime
from unittest.mock import MagicMock

from django.db.models import F
from django.db.models.functions import ExtractYear, Substr
from django.test import TestCase

from model_bakery import baker

import django_virtual_models as v

from . import db_utils
from .models import (
    Assignment,
    CompletedLesson,
    Course,
    Facilitator,
    Lesson,
    LiveCourse,
    SQArrayAgg,
    User,
)


class NestedUserAssignment(v.VirtualModel):
    email = v.Expression(F("user__email"))
    lessons_total = v.Annotation(lambda qs, **kwargs: qs.annotate_lessons_total())
    lessons_completed_total = v.Annotation(
        lambda qs, **kwargs: qs.annotate_lessons_completed_total()
    )

    def get_prefetch_queryset(self, user=None, **kwargs):
        if user is None:
            return Assignment.objects.none()
        return Assignment.objects.filter(user=user)


class VirtualCourse(v.VirtualModel):
    small_description = v.Expression(Substr("description", 1, 128))
    created_by = v.NestedJoin(model_cls=User)
    facilitator_emails = v.Expression(SQArrayAgg(F("facilitators__email")))
    user_assignment = NestedUserAssignment(
        manager=Assignment.objects, lookup="assignments", to_attr="user_assignment"
    )
    assignments = v.VirtualModel(manager=Assignment.objects)
    noop_field = v.NoOp()

    class Meta:
        model = Course
        deferred_fields = ["description"]


class VirtualModelsTest(TestCase):
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

    def test_implicit_full_lookup_has_no_n_plus_one_queries(self):
        virtual_course = VirtualCourse(user=self.user)
        qs = Course.objects.order_by("created")

        optimized_qs = virtual_course.get_optimized_queryset(qs=qs, lookup_list=[])
        with self.assertNumQueries(3):
            course_list = list(optimized_qs)
            assert len(course_list) == 3

            # access attrs to ensure no N+1 queries are made
            for course in course_list:
                assert isinstance(course.small_description, str)
                assert isinstance(course.created_by, User)
                assert isinstance(course.facilitator_emails, list)
                assert isinstance(course.facilitator_emails[0], str)
                assert isinstance(course.user_assignment[0], Assignment)
                assert len(list(course.assignments.all())) == 4

    def test_explicit_full_virtual_lookup_has_no_n_plus_one_queries(self):
        virtual_course = VirtualCourse(user=self.user)
        qs = Course.objects.order_by("created")
        # full lookup list of annotations/joins/prefetches based on VirtualCourse
        lookup_list = [
            "small_description",
            "created_by",
            "facilitator_emails",
            "user_assignment__email",
            "user_assignment__lessons_total",
            "user_assignment__lessons_completed_total",
            "assignments",
        ]

        optimized_qs = virtual_course.get_optimized_queryset(qs=qs, lookup_list=lookup_list)
        with self.assertNumQueries(3):
            course_list = list(optimized_qs)
            assert len(course_list) == 3

            # access attrs to ensure no N+1 queries are made
            for course in course_list:
                assert isinstance(course.small_description, str)
                assert isinstance(course.created_by, User)
                assert isinstance(course.facilitator_emails, list)
                assert isinstance(course.facilitator_emails[0], str)
                assert isinstance(course.user_assignment[0], Assignment)
                assert len(list(course.assignments.all())) == 4

    def test_concrete_fields_in_lookup_has_no_n_plus_one_queries(self):
        virtual_course = VirtualCourse(user=self.user)
        qs = Course.objects.order_by("created")
        lookup_list = [
            "created",
            "user_assignment__created",
            "assignments__created",
        ]

        optimized_qs = virtual_course.get_optimized_queryset(qs=qs, lookup_list=lookup_list)
        with self.assertNumQueries(3):
            course_list = list(optimized_qs)
            assert len(course_list) == 3

            # access concrete attrs to ensure no N+1 queries are made
            for course in course_list:
                assert isinstance(course.created, datetime)
                assert isinstance(course.user_assignment[0].created, datetime)
                assert isinstance(course.assignments.all()[0].created, datetime)

    def test_ignore_virtual_fields_not_in_lookup(self):
        virtual_course = VirtualCourse(user=self.user)
        qs = Course.objects.order_by("created")
        lookup_list = ["small_description"]

        optimized_qs = virtual_course.get_optimized_queryset(qs=qs, lookup_list=lookup_list)
        with self.assertNumQueries(1):
            course_list = list(optimized_qs)
            assert len(course_list) == 3

            for course in course_list:
                assert isinstance(course.small_description, str)
                assert not db_utils.is_preloaded(course, "created_by")
                assert not db_utils.is_preloaded(course, "facilitator_emails")
                assert not db_utils.is_preloaded(course, "user_assignment")
                assert not db_utils.is_preloaded(course, "assignments")

    def test_pass_user_and_kwargs_to_annotation(self):
        class MockedVirtualCourse(v.VirtualModel):
            something = v.Annotation(
                lambda qs, user, **kwargs: qs.annotate_something(user=user, **kwargs)
            )

            class Meta:
                model = Course
                deferred_fields = ["name", "description"]

        virtual_course = MockedVirtualCourse(user=self.user)
        mock_qs = MagicMock()
        extra_kwarg_0 = object()
        extra_kwarg_1 = object()
        virtual_course.get_optimized_queryset(
            qs=mock_qs,
            lookup_list=[],
            extra_kwarg_0=extra_kwarg_0,
            extra_kwarg_1=extra_kwarg_1,
        )

        mock_qs.annotate_something.assert_called_once_with(
            user=self.user,
            extra_kwarg_0=extra_kwarg_0,
            extra_kwarg_1=extra_kwarg_1,
        )

    def test_returns_right_results(self):
        virtual_course = VirtualCourse(user=self.user)
        qs = Course.objects.order_by("created")
        # full lookup list of annotations/joins/prefetches based on VirtualCourse
        lookup_list = [
            "small_description",
            "created_by",
            "facilitator_emails",
            "user_assignment__email",
            "user_assignment__lessons_total",
            "user_assignment__lessons_completed_total",
            "assignments",
        ]

        optimized_qs = virtual_course.get_optimized_queryset(qs=qs, lookup_list=lookup_list)
        course_list = list(optimized_qs)

        # assert data is correct and in correct order
        for course, expected_course in zip(course_list, self.courses):
            assert course.small_description == expected_course.description[:128]
            assert course.created_by == expected_course.created_by
            assert sorted(course.facilitator_emails) == sorted(
                [f.user.email for f in self.course_to_related[course]["facilitators"]]
            )
            assert course.user_assignment[0] == self.course_to_related[course]["user_assignment"]
            assert list(course.assignments.all()) == self.course_to_related[course]["assignments"]

        # assert user_assignment annotations
        for course, expected_course in zip(course_list, self.courses):
            user_assignment = course.user_assignment[0]
            assert user_assignment.email == self.user.email
            assert user_assignment.lessons_total == 3

            if course == self.courses[0]:
                # on setUp we completed all lessons minus 1 for self.user on the first course
                assert user_assignment.lessons_completed_total == 2
            else:
                assert user_assignment.lessons_completed_total == 0

    def test_inheritance(self):
        class SimpleVirtualCourse(v.VirtualModel):
            small_description = v.Expression(Substr("description", 1, 128))

            class Meta:
                model = Course
                deferred_fields = ["name", "description"]

        class SimpleVirtualLiveCourse(SimpleVirtualCourse):
            year = v.Expression(ExtractYear("dt"))

            class Meta:
                model = LiveCourse

        assert list(SimpleVirtualCourse().declared_fields.keys()) == ["small_description"]
        assert list(SimpleVirtualLiveCourse().declared_fields.keys()) == [
            "small_description",
            "year",
        ]
        assert SimpleVirtualCourse().deferred_fields == {"name", "description"}
        assert SimpleVirtualLiveCourse().deferred_fields == set()
        assert SimpleVirtualCourse().model_cls == Course
        assert SimpleVirtualLiveCourse().model_cls == LiveCourse

    def test_noop(self):
        virtual_course = VirtualCourse(user=self.user)
        qs = Course.objects.order_by("created")
        lookup_list = ["noop_field"]

        optimized_qs = virtual_course.get_optimized_queryset(qs=qs, lookup_list=lookup_list)

        # assert nothing has changed
        assert list(optimized_qs) == list(qs)

        # assert there's no `noop_field`
        assert not hasattr(qs[0], "noop_field")

    def test_deferred_fields(self):
        class SimpleVirtualCourse(v.VirtualModel):
            small_description = v.Expression(Substr("description", 1, 128))

            class Meta:
                model = Course
                deferred_fields = ["description", "settings"]

        class SimpleVirtualLesson(v.VirtualModel):
            course = SimpleVirtualCourse(manager=Course.objects)

            class Meta:
                model = Lesson
                deferred_fields = ["content"]

        virtual_lesson = SimpleVirtualLesson()
        qs = Lesson.objects.order_by("created")
        lookup_list = ["course__small_description"]

        optimized_qs = virtual_lesson.get_optimized_queryset(qs=qs, lookup_list=lookup_list)
        # assert queries are made to get deferred fields
        lesson_list = list(optimized_qs)
        with self.assertNumQueries(3) as ctx:
            lesson_list[0].content  # query 1
            lesson_list[0].course.description  # query 2
            lesson_list[0].course.settings  # query 3
            lesson_list[0].course.small_description  # no query
        assert "content" in ctx.captured_queries[0]["sql"]
        assert "description" in ctx.captured_queries[1]["sql"]
        assert "settings" in ctx.captured_queries[2]["sql"]

    def test_nested_virtual_model_prefetch_keeps_back_reference_to_avoid_n_plus_one(self):
        class SimpleVirtualAssignment(v.VirtualModel):
            class Meta:
                model = Assignment
                # Despite being deferred, user will be kept in the SELECT
                # because it's where the prefetch comes from.
                # See code at `VirtualModel.hydrate_queryset`, look for `back_reference`:
                deferred_fields = ["user", "user_id"]

        class SimpleVirtualUser(v.VirtualModel):
            assignments = SimpleVirtualAssignment(manager=Assignment.objects)

            class Meta:
                model = User

        virtual_user = SimpleVirtualUser()
        qs = User.objects.order_by("created")
        lookup_list = ["assignments"]

        optimized_qs = virtual_user.get_optimized_queryset(qs=qs, lookup_list=lookup_list)
        with self.assertNumQueries(2):
            user_list = list(optimized_qs)
            assert len(user_list) > 1
        with self.assertNumQueries(0):
            for user in user_list:
                for assignment in user.assignments.all():
                    assert isinstance(assignment, Assignment)

    def test_full_prefetch_when_using_only_the_nested_virtual_model_field_name(self):
        class SimpleVirtualCourse(v.VirtualModel):
            small_description = v.Expression(Substr("description", 1, 128))

            class Meta:
                model = Course
                deferred_fields = ["description", "settings"]

        class SimpleVirtualLesson(v.VirtualModel):
            course = SimpleVirtualCourse(manager=Course.objects)

            class Meta:
                model = Lesson
                deferred_fields = ["content"]

        virtual_lesson = SimpleVirtualLesson()
        qs = Lesson.objects.order_by("created")
        lookup_list = ["course"]

        optimized_qs = virtual_lesson.get_optimized_queryset(qs=qs, lookup_list=lookup_list)
        # assert full prefetch gets all concrete, virtual and deferred fiedls
        with self.assertNumQueries(2):
            lesson_list = list(optimized_qs)
            assert len(lesson_list) > 1
        with self.assertNumQueries(0):
            for lesson in lesson_list:
                assert isinstance(lesson.course, Course)
                assert isinstance(lesson.course.small_description, str)
                assert isinstance(lesson.course.description, str)
                assert isinstance(lesson.course.settings, dict)

    def test_deep_nested_join_in_nested_virtual_model(self):
        class SimpleVirtualAssignment(v.VirtualModel):
            course = v.NestedJoin(model_cls=Course)

            class Meta:
                model = Assignment

        class SimpleVirtualUser(v.VirtualModel):
            assignments = SimpleVirtualAssignment(manager=Assignment.objects)

            class Meta:
                model = User

        virtual_user = SimpleVirtualUser()
        qs = User.objects.order_by("created")
        lookup_list = ["assignments__course__created_by"]

        optimized_qs = virtual_user.get_optimized_queryset(qs=qs, lookup_list=lookup_list)
        with self.assertNumQueries(2):
            user_list = list(optimized_qs)
            assert len(user_list) > 1
        with self.assertNumQueries(0):
            for user in user_list:
                for assignment in user.assignments.all():
                    assert isinstance(assignment, Assignment)
                    assert isinstance(assignment.course, Course)
                    assert isinstance(assignment.course.created_by, User)

    def test_nested_join_supports_lookups_of_concrete_fields(self):
        class VirtualLesson(v.VirtualModel):
            course = v.NestedJoin(model_cls=Course)

            class Meta:
                model = Lesson

        virtual_lesson = VirtualLesson()
        qs = Lesson.objects.all()
        lookup_list = ["course__created_by"]

        optimized_qs = virtual_lesson.get_optimized_queryset(qs=qs, lookup_list=lookup_list)
        with self.assertNumQueries(1):
            lesson_list = list(optimized_qs)
            assert len(lesson_list) == 9

            for lesson in lesson_list:
                assert isinstance(lesson.course.created_by, User)

    def test_deep_nested_join_supports_lookups_of_concrete_fields(self):
        class SimpleVirtualCompletedLesson(v.VirtualModel):
            lesson = v.NestedJoin(model_cls=Lesson)

            class Meta:
                model = CompletedLesson

        virtual_completed_lesson = SimpleVirtualCompletedLesson()
        qs = CompletedLesson.objects.all()
        lookup_list = ["lesson__course__created_by"]

        optimized_qs = virtual_completed_lesson.get_optimized_queryset(
            qs=qs, lookup_list=lookup_list
        )
        with self.assertNumQueries(1):
            completed_lesson_list = list(optimized_qs)
            assert len(completed_lesson_list) == 2

            for completed_lesson in completed_lesson_list:
                assert isinstance(completed_lesson.lesson.course.created_by, User)

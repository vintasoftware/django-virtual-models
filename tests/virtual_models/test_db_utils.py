from django.test import TestCase

from model_bakery import baker

from .db_utils import is_preloaded
from .models import Assignment, Course, Lesson


class DBUtilsTest(TestCase):
    def test_is_preloaded_with_no_model(self):
        assert not is_preloaded(None, "foo")

    def test_is_preloaded_with_no_attribute(self):
        course = baker.make(Course, _fill_optional=True)
        instance = Course.objects.get(id=course.id)
        with self.assertNumQueries(0):
            assert not is_preloaded(instance, None)

    def test_is_preloaded_with_non_attribute(self):
        course = baker.make(Course, _fill_optional=True)
        instance = Course.objects.get(id=course.id)
        with self.assertNumQueries(0):
            assert not is_preloaded(instance, "invalid_attribute")

    def test_is_preloaded_with_non_foreign_key_attribute(self):
        course = baker.make(Course, _fill_optional=True)
        instance = Course.objects.get(id=course.id)
        with self.assertNumQueries(0):
            assert not is_preloaded(instance, "name")

    def test_is_preloaded_with_non_preloaded_foreign_key_attribute(self):
        course = baker.make(Course, _fill_optional=True)
        instance = Course.objects.get(id=course.id)
        with self.assertNumQueries(0):
            assert not is_preloaded(instance, "created_by")

    def test_is_preloaded_with_non_preloaded_one_to_many_attribute(self):
        lessons = baker.make(Lesson, _fill_optional=True, _quantity=2)
        instance = Course.objects.get(id=lessons[0].course.id)
        with self.assertNumQueries(0):
            assert not is_preloaded(instance, "lessons")

    def test_is_preloaded_with_non_preloaded_many_to_many_attribute(self):
        course = baker.make(Course, _fill_optional=True, make_m2m=True)
        instance = Course.objects.get(id=course.id)
        with self.assertNumQueries(0):
            assert not is_preloaded(instance, "facilitators")

    def test_is_preloaded_with_preloaded_foreign_key_attribute(self):
        course = baker.make(Course, _fill_optional=True)
        instance = Course.objects.select_related("created_by").get(id=course.id)
        with self.assertNumQueries(0):
            assert is_preloaded(instance, "created_by")

    def test_is_preloaded_with_preloaded_one_to_many_attribute(self):
        lessons = baker.make(Lesson, _fill_optional=True, _quantity=2)
        instance = Course.objects.prefetch_related("lessons").get(id=lessons[0].course.id)
        with self.assertNumQueries(0):
            assert is_preloaded(instance, "lessons")

    def test_is_preloaded_with_preloaded_many_to_many_attribute(self):
        course = baker.make(Course, _fill_optional=True, make_m2m=True)
        instance = Course.objects.prefetch_related("facilitators").get(id=course.id)
        with self.assertNumQueries(0):
            assert is_preloaded(instance, "facilitators")

    def test_is_preloaded_without_named_attribute(self):
        assignment = baker.make(Assignment, _fill_optional=True, make_m2m=True)
        instance = Assignment.objects.get(id=assignment.id)

        assert not is_preloaded(instance, "lessons_total")

    def test_is_preloaded_with_named_attribute(self):
        assignment = baker.make(Assignment, _fill_optional=True, make_m2m=True)
        instance = Assignment.objects.annotate_lessons_total().get(id=assignment.id)

        assert is_preloaded(instance, "lessons_total")

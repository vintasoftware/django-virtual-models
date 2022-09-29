from django.test import TestCase

from model_bakery import baker

from django_virtual_models.query_capture.capture import native_query_capture

from ..virtual_models.models import Course, Lesson


class NativeQueryCaptureTests(TestCase):
    def setUp(self):
        super().setUp()
        courses = baker.make(Course, _fill_optional=False, _quantity=3)
        for course in courses:
            baker.make(Lesson, course=course, _fill_optional=False, _quantity=3)

    def test_capture_query_in_context_manager(self):
        with native_query_capture() as ctx:
            for course in list(Course.objects.all()):
                list(course.lessons.all())

        self.assertEqual(len(ctx), 4)

        assert 'FROM "virtual_models_course"' in ctx.captured_queries[0]["sql"]
        for i in range(1, 4):
            assert 'FROM "virtual_models_lesson"' in ctx.captured_queries[i]["sql"]

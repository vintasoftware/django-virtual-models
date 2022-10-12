from __future__ import annotations

from django.db import models
from django.db.models import Aggregate, OuterRef

from typing_extensions import Annotated

from django_virtual_models.prefetch import hints


class SQArrayAgg(Aggregate):
    function = "JSON_GROUP_ARRAY"
    allow_distinct = True

    @property
    def output_field(self):
        return models.JSONField(self.source_expressions[0].output_field)

    def convert_value(self, value, expression, connection):
        if not value:
            return []
        return value


class SQCount(models.Subquery):
    template = "(SELECT COUNT(*) FROM (%(subquery)s) %(count_variable_name)s)"
    output_field = models.PositiveIntegerField()

    def __init__(self, subquery, *args, **kwargs):
        count_variable_name = kwargs.pop("count_variable_name", "_count")
        super().__init__(subquery.values_list("id", flat=True), *args, **kwargs)
        if hasattr(self, "extra") and isinstance(self.extra, dict):
            self.extra["count_variable_name"] = count_variable_name


class TimeStampedModel(models.Model):
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    modified = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        abstract = True


class User(TimeStampedModel):
    email = models.EmailField()


class Course(TimeStampedModel):
    name = models.TextField()
    description = models.TextField()
    created_by = models.ForeignKey(
        "User",
        related_name="created_courses",
        on_delete=models.PROTECT,
    )
    facilitators = models.ManyToManyField(
        "User",
        through="Facilitator",
        blank=True,
        related_name="facilitated_courses",
    )
    assignees = models.ManyToManyField(
        "User",
        through="Assignment",
        blank=True,
        related_name="assigned_courses",
    )
    settings = models.JSONField(default=dict, blank=True)

    @hints.no_deferred_fields()
    def name_title_case(self):
        return self.name.title()

    @property
    def description_first_line(self: Annotated[Course, hints.Virtual("description")]):
        try:
            return self.description.splitlines()[0]
        except IndexError:
            return ""


class Lesson(TimeStampedModel):
    course = models.ForeignKey(
        "Course",
        related_name="lessons",
        on_delete=models.CASCADE,
    )
    title = models.TextField()
    content = models.TextField()


class Facilitator(TimeStampedModel):
    user = models.ForeignKey("User", on_delete=models.PROTECT)
    course = models.ForeignKey("course", on_delete=models.CASCADE)


class AssignmentQueryset(models.QuerySet):
    def annotate_lessons_total(self):
        # If we used this naive code below, it would make wrong joins:
        # # lessons_total=Count("course__lessons", distinct=True),
        # Instead, use SQCount:
        return self.annotate(
            lessons_total=SQCount(
                Lesson.objects.filter(course=OuterRef("course_id")),
            ),
        )

    def annotate_lessons_completed_total(self):
        # If we used this naive code below, it would make wrong joins:
        # # lessons_completed_total=Count("completed_lessons", distinct=True),
        # Instead, use SQCount:
        return self.annotate(
            lessons_completed_total=SQCount(
                CompletedLesson.objects.filter(assignment=OuterRef("id")),
            ),
        )


AssignmentManager = models.Manager.from_queryset(AssignmentQueryset)


class Assignment(TimeStampedModel):
    user = models.ForeignKey(
        "User",
        related_name="assignments",
        on_delete=models.CASCADE,
    )
    course = models.ForeignKey(
        "Course",
        related_name="assignments",
        on_delete=models.CASCADE,
    )
    completed_lessons = models.ManyToManyField(
        "Lesson",
        through="CompletedLesson",
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["created"]

    objects = AssignmentManager()

    @property
    def last_completed_lesson_name(
        self: Annotated[Assignment, hints.Virtual("course", "completed_lessons")]
    ):
        lessons = list(self.completed_lessons.all())
        lessons.sort(key=lambda lesson: lesson.created)
        last_lesson = lessons[-1]
        return f"{self.course.name} - {last_lesson.name}"


class CompletedLesson(TimeStampedModel):
    assignment = models.ForeignKey("Assignment", on_delete=models.CASCADE)
    lesson = models.ForeignKey("Lesson", on_delete=models.CASCADE)


class LiveCourse(Course):
    dt = models.DateTimeField()

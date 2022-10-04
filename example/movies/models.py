from django.db import models


class Person(models.Model):
    name = models.CharField(max_length=255, unique=True)


class Nomination(models.Model):
    award = models.CharField(max_length=255)
    category = models.CharField(max_length=255)
    year = models.PositiveSmallIntegerField()
    person = models.ForeignKey(Person, related_name="nominations", on_delete=models.CASCADE)
    movie = models.ForeignKey("Movie", related_name="nominations", on_delete=models.CASCADE)
    is_winner = models.BooleanField()


class PersonDirector(models.Model):
    movie = models.ForeignKey("Movie", on_delete=models.CASCADE)
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    order = models.PositiveSmallIntegerField()

    class Meta:
        index_together = [("movie", "order")]
        ordering = ["movie", "order"]


class Movie(models.Model):
    name = models.CharField(max_length=255)
    directors = models.ManyToManyField(
        Person,
        through=PersonDirector,
        blank=True,
        related_name="directed_movies",
    )

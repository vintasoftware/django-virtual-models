from django.contrib import admin

from movies.models import Movie, Nomination, Person, PersonDirector

admin.site.register(Movie)
admin.site.register(Person)
admin.site.register(Nomination)
admin.site.register(PersonDirector)

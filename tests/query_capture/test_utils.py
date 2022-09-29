import logging

from model_bakery import baker

from django_virtual_models.query_capture.utils import max_query_count

from ..virtual_models.models import Course


def test_warning_when_only_log_is_true(db, caplog):
    baker.make(Course, _fill_optional=False, _quantity=3)

    with caplog.at_level(logging.WARNING):
        with max_query_count(only_log=True, affected_cls_or_fn_name="test"):
            list(Course.objects.all())

    assert len(caplog.records) == 1
    assert "Possible N+1 problem on test" in caplog.records[0].msg
    assert "expected=0" in caplog.records[0].msg
    assert "actual=1" in caplog.records[0].msg

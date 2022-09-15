from django_virtual_models.utils import one_level_lookup_list, str_remove_prefix, unique_keep_order


def test_unique_keep_order():
    generator_1 = (x for x in (7, 7, 6, 5, 5, 5))
    assert unique_keep_order(generator_1) == [7, 6, 5]

    generator_2 = (x for x in (1, 2, 3))
    assert unique_keep_order(generator_2) == [1, 2, 3]

    assert unique_keep_order([]) == []


def test_one_level_lookup_list():
    assert one_level_lookup_list(["a", "b", "c__foo", "d__bar", "e__foo__bar"]) == [
        "a",
        "b",
        "c",
        "d",
        "e",
    ]

    assert one_level_lookup_list([]) == []


def test_str_remove_prefix():
    assert str_remove_prefix("aaafoo", "aaa") == "foo"

    assert str_remove_prefix("aaa", "aaa") == ""

    assert str_remove_prefix("aaa", "foo") == "aaa"

    assert str_remove_prefix("", "aaa") == ""

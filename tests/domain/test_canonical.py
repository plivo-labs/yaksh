import pytest

from yaksh.domain.canonical import canonical, contains


@pytest.mark.parametrize(
    ("spoken", "written"),
    [
        ("five five five, oh one four two", "555 0142"),
        ("Tuesday, October sixth at two thirty p.m.", "tuesday october 6 at 2:30 pm"),
        ("October 6th at 2:30 PM", "october 6 at 2:30 pm"),
        ("March fourteenth, nineteen ninety.", "march 14 1990"),
        ("A new patient cleaning is eighty dollars.", "a new patient cleaning is 80 dollars"),
        ("It costs $95.", "it costs 95"),
        ("ninety-five dollars", "95 dollars"),
        ("twenty twenty-six", "2026"),
        ("two hundred and five", "205"),
        ("Oh, okay.", "oh okay"),
        ("one thousand two hundred fifty dollars", "1250 dollars"),
        ("two thousand five hundred", "2500"),
        ("$1,250 or 10,000", "1250 or 10000"),
        ("two hundred fifty five", "255"),
        ("at 4p.m. or 8a.m", "at 4 pm or 8 am"),
        ("5.30 pm", "5:30 pm"),
        ("nine oh five, twelve oh five, nineteen oh five", "9:05 12:05 1905"),
        ("one second please", "1 second please"),
        ("मैंने booking कर दी, ५५५", "मैंने booking कर दी 555"),
    ],
)
def test_numbers_dates_and_times_read_the_same_however_they_were_written(
    spoken: str, written: str
) -> None:
    assert canonical(spoken) == written


def test_a_quote_is_found_in_its_turn_however_either_writes_the_numbers() -> None:
    assert contains("A new patient cleaning is eighty dollars.", "$80")
    assert contains("It's five five five, oh one four two.", "555 0142")
    assert contains("It is twenty five dollars.", "twenty")
    assert not contains("booking कर दो", "booking कर दी")
    assert not contains("नहाना है", "नहीं")

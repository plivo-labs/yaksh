"""The prompts, as Jinja templates in templates/: one file for each prompt."""

from jinja2 import Environment, PackageLoader, StrictUndefined

ENVIRONMENT = Environment(
    loader=PackageLoader("yaksha.simulation"),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def render(name: str, /, **values: object) -> str:
    """The template `name` filled in with `values`, without the newlines after its last line.
    A value the template uses but `values` lacks is an error, never a blank."""
    return ENVIRONMENT.get_template(name).render(values).rstrip("\n")

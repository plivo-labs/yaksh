import typer
import uvicorn

from truman.config import settings

cli = typer.Typer(no_args_is_help=True, add_completion=False)


@cli.callback()
def main_callback() -> None:
    pass


@cli.command()
def api(host: str = settings.api_host, port: int = settings.api_port, reload: bool = False) -> None:
    uvicorn.run("truman.api:create_app", factory=True, host=host, port=port, reload=reload)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()

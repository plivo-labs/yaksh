import typer
import uvicorn

from truman.config import Settings
from truman.db.migrate import upgrade_to_head

cli = typer.Typer(no_args_is_help=True, add_completion=False)


@cli.callback()
def main_callback() -> None:
    pass


@cli.command()
def api(host: str | None = None, port: int | None = None, reload: bool = False) -> None:
    settings = Settings()
    uvicorn.run(
        "truman.api:create_app",
        factory=True,
        host=host or settings.api_host,
        port=port or settings.api_port,
        reload=reload,
    )


@cli.command()
def migrate() -> None:
    upgrade_to_head(str(Settings().database_url))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()

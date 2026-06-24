import click
import uvicorn


@click.command()
@click.option("--host",  default="localhost", help="Hostname, e.g. 'localhost' or '0.0.0.0'")
@click.option("--port",  default=8888,        help="Listen port")
@click.option("--debug", default=False, is_flag=True, help="Enable debug / reload")
def main(host, port, debug):
    uvicorn.run(
        "molior.fastapi.app:create_app",
        factory=True,
        host=host,
        port=port,
        log_level="debug" if debug else "info",
        loop="asyncio",  # uvloop does not support set_child_watcher (needed by Launchy)
    )


if __name__ == "__main__":
    main()

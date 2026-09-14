from worlds.LauncherComponents import Component, Type, components, launch

from .data import GAME_NAME


def run_client(*args: str) -> None:
    from .client.launch import launch_phase10_client

    launch(launch_phase10_client, name=f"{GAME_NAME} Client", args=args)


components.append(
    Component(
        f"{GAME_NAME} Client",
        func=run_client,
        game_name=GAME_NAME,
        component_type=Type.CLIENT,
        supports_uri=True,
    )
)

from worlds.LauncherComponents import Component, Type, components, launch


def run_client(*args: str) -> None:
    from .client.launch import launch_phase10_client

    launch(launch_phase10_client, name="Phase 10 Client", args=args)


components.append(
    Component(
        "Phase 10 Client",
        func=run_client,
        game_name="Phase 10",
        component_type=Type.CLIENT,
        supports_uri=True,
    )
)

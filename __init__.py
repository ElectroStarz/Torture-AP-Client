from worlds.AutoWorld import World
from worlds.LauncherComponents import Component, Type, components, launch


def run_client(*args: str) -> None:
    from .client import launch_torture_client
    launch(launch_torture_client, name="Torture Client", args=args)


components.append(
    Component(
        "Torture Client",
        func=run_client,
        component_type=Type.CLIENT,
    )
)


class TortureWorld(World):
    """Custom Built Dashboard for ElectroStarz's Torture Asyncs and/or other people's enjoyment"""
    game = "Torture Client"
    item_name_to_id = {}
    location_name_to_id = {}
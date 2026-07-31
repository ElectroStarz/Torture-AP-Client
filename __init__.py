from worlds.AutoWorld import World
from worlds.LauncherComponents import Component, Type, components, launch, icon_paths


def run_admin_client(*args: str) -> None:
    from .torture_admin.admin_client import launch_torture_admin_client
    launch(launch_torture_admin_client, name="Torture Admin Client", args=args)

def run_user_client(*args: str) -> None:
    from .torture_user.user_client import launch_torture_user_client
    launch(launch_torture_user_client, name="Torture User Client", args=args)

icon_paths["AdminIcon"] = f"ap:{__name__}/torture_admin/admin_icon.png"
components.append(
    Component(
        "Torture Admin Client",
        func=run_admin_client,
        component_type=Type.CLIENT,
        icon="AdminIcon"
    )
)

icon_paths["UserIcon"] = f"ap:{__name__}/torture_user/user_icon.png"
components.append(
    Component(
        "Torture User Client",
        func=run_user_client,
        component_type=Type.CLIENT,
        icon="UserIcon"
    )
)


class TortureWorld(World):
    """Inflict horrible pain and suffering on your friends with this :]"""
    game = "Torture Client"
    item_name_to_id = {}
    location_name_to_id = {}
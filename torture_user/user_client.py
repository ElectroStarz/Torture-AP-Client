import asyncio
import logging
import multiprocessing
import sys
import webbrowser
from typing import Any


import Utils
from CommonClient import ClientCommandProcessor, CommonContext, get_base_parser, gui_enabled, handle_url_arg, \
    server_loop

logger = logging.getLogger("Client")

class TortureUserCommandProcessor(ClientCommandProcessor):
    ctx: "TortureUserContext"

    def __init__(self, ctx: "TortureUserContext"):
        super().__init__(ctx)

    def _cmd_torture_help(self):
        """Use this command if you're struggling with how to use this"""

        logger.info("Check your browser!")
        webbrowser.open_new_tab("https://www.github.com/ElectroStarz/Torture-AP-Client/blob/main/docs/help.md")


class TortureUserContext(CommonContext):
    tags = CommonContext.tags | {"Torture User"}
    game = ""
    games_present: list[str] = []

    items_handling = 0b111
    want_slot_data = False

    def __init__(self, server_address: str | None = None, password: str | None = None) -> None:
        super().__init__(server_address, password)

    async def server_auth(self, password_requested: bool = False):
        if password_requested and not self.password:
            await super(TortureUserContext, self).server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    def on_package(self, cmd: str, args: dict):
        super().on_package(cmd, args)

    async def disconnect(self, allow_autoreconnect: bool = False):
        await super().disconnect(allow_autoreconnect)

    def make_gui(self):
        ui = super().make_gui()
        ui.base_title = "TEST"
        return ui


def launch_torture_user_client(*args):
    Utils.init_logging("Torture User Client")

    async def main(main_args):
        ctx = TortureUserContext(main_args.connect, main_args.password)
        ctx.auth = main_args.name
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="Server Loop")

        if gui_enabled:
            ctx.run_gui()
        ctx.run_cli()

        await ctx.exit_event.wait()
        ctx.server_address = None

    import colorama

    parser = get_base_parser(description="Archipelago Torture User Client.")
    parser.add_argument("--name", default=None, help="Slot Name to connect as.")
    parser.add_argument("url", nargs="?", help="Archipelago connection url")

    launch_args = handle_url_arg(parser.parse_args(args))

    colorama.just_fix_windows_console()
    asyncio.run(main(launch_args))
    colorama.deinit()

if __name__ == "__main__":
    multiprocessing.freeze_support()
    launch_torture_user_client(*sys.argv[1:])
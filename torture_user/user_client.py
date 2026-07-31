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

    def _cmd_torture(self):
        """Enables and disables Torture functionality"""

        self.ctx.torture = not self.ctx.torture

        if self.ctx.torture:
            self.ctx.tags.add("Torture User Client")
            logger.info("Enabled Torture!")
        else:
            self.ctx.tags.discard("Torture User Client")
            logger.info("Disabled Torture!")

        if self.ctx.server:
            update_packet = {
                "cmd": "ConnectUpdate",
                "tags": list(self.ctx.tags)
            }
            asyncio.create_task(self.ctx.send_msgs([update_packet]))

    def _cmd_torture_help(self):
        """Use this command if you're struggling with the Torture User Client functions"""

        logger.info("Check your browser!")
        webbrowser.open_new_tab("https://www.github.com/ElectroStarz/Torture-AP-Client/blob/main/docs/help.md")


class TortureUserContext(CommonContext):
    command_processor = TortureUserCommandProcessor
    tags = CommonContext.tags | {"TextOnly"}
    game = ""
    games_present: list[str] = []

    items_handling = 0b111
    want_slot_data = False

    def __init__(self, server_address: str | None = None, password: str | None = None) -> None:
        super().__init__(server_address, password)
        self.torture = False

    async def server_auth(self, password_requested: bool = False):
        if password_requested and not self.password:
            await super(TortureUserContext, self).server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    def on_package(self, cmd: str, args: dict):
        super().on_package(cmd, args)

        if cmd == "Bounced":
            data = args.get("data", None)
            if data is not None:
                action = data["action"]
                if action == "pm":
                    self.display_pm(data["content"])
                elif action == "request_status":
                    update_packet = {
                        "cmd": "Bounce",
                        "games": ["Torture Client"],
                        "data": {
                            "action": "status_reply",
                            "slot": self.slot,
                            "tags": list(self.tags)
                        }
                    }
                    asyncio.create_task(self.send_msgs([update_packet]))


    async def disconnect(self, allow_autoreconnect: bool = False):
        await super().disconnect(allow_autoreconnect)

    def make_gui(self):
        ui = super().make_gui()
        ui.base_title = "Archipelago Torture User Client | AP Version"
        return ui

    def display_pm(self, text):
        if self.ui is not None:
            self.ui.print_json(text)


def launch_torture_user_client(*args):
    Utils.init_logging("Torture User Client")

    async def main(main_args):
        ctx = TortureUserContext(main_args.connect, main_args.password)
        ctx.auth = main_args.name
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="Server Loop")
        ctx.torture = True
        ctx.tags.add("Torture User Client")

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
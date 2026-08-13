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


# Taken from MarioManTAW's Teet Client with permission
def sm64ify(input: str, recent: str = "☺") -> tuple[str, str]:
    output: str = ""
    for x in input:
        if x in "!#%&*+,-.?":
            output += recent
        elif x.upper() in "JQVXZ":
            output += recent.upper() if x == x.upper() else recent.lower()
        elif x.upper() in "ABCDEFGHIKLMNOPRSTUWY0123456789":
            output += x
            recent = x
        elif x.strip() == "":
            output += x
        else:
            output += " "
    return output, recent


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
        webbrowser.open_new_tab("https://github.com/ElectroStarz/Torture-AP-Client/blob/main/docs/user_help.md")


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
        self.teet_status = False

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
                action = data.get("action", "")
            else:
                action = ""

            if action == "pm":
                if self.ui:
                    self.ui.print_json(data["content"])

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


    def on_print(self, args: dict):
        if self.teet_status:
            args["text"] = sm64ify(args["text"])[0]

        super().on_print(args)

    def on_print_json(self, args: dict):

        if self.teet_status:
            recent = "☺"
            for d in args["data"]:
                if "type" in d:
                    if d["type"] == "player_id":
                        d["color"] = "magenta" if self.slot_concerns_self(int(d["text"])) else "yellow"
                        d["text"] = self.player_names[int(d["text"])]
                        d["type"] = "color"
                    elif d["type"] == "item_id":
                        flags = d["flags"]
                        if flags == 0:
                            d["color"] = 'cyan'
                        elif flags & 0b001:  # Advancement
                            d["color"] = 'plum'
                        elif flags & 0b010:  # Useful
                            d["color"] = 'slateblue'
                        elif flags & 0b100:  # Trap
                            d["color"] = 'salmon'
                        else:
                            d["color"] = 'cyan'
                        d["text"] = self.item_names.lookup_in_slot(int(d["text"]), d["player"])
                        d["type"] = "color"
                    elif d["type"] == "location_id":
                        d["color"] = "green"
                        d["text"] = self.location_names.lookup_in_slot(int(d["text"]), d["player"])
                        d["type"] = "color"
                d["text"], recent = sm64ify(d["text"], recent)

        return super().on_print_json(args)

    async def disconnect(self, allow_autoreconnect: bool = False):
        await super().disconnect(allow_autoreconnect)

    def make_gui(self):
        ui = super().make_gui()
        ui.base_title = "Archipelago Torture User Client | AP Version"
        return ui

def launch_torture_user_client(*args):
    Utils.init_logging("Torture User Client")

    async def main(main_args):
        ctx = TortureUserContext(main_args.connect, main_args.password)
        ctx.auth = main_args.name
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="Server Loop")
        # We're launching from the component, not importing so we
        # can assume the user will want the Torture functionality
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
import asyncio
import logging
import multiprocessing
import os
import random
import sys
from typing import Any
import webbrowser

from NetUtils import JSONMessagePart
from kvui import GameManager
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.properties import StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.checkbox import CheckBox

import Utils
from CommonClient import ClientCommandProcessor, CommonContext, get_base_parser, gui_enabled, handle_url_arg, \
    server_loop

logger = logging.getLogger("Client")

class TortureDashboard(BoxLayout):
    room_info = StringProperty("Disconnected")
    player_info = StringProperty("Disconnected")

    def __init__(self, ctx: "TortureClientContext", **kwargs):
        super().__init__(**kwargs)
        self.ctx = ctx
        self.selected_players = {}
        self._last_player_count = 0
        # Schedule the info updaters to run every 0.5 seconds
        Clock.schedule_interval(self.update_dashboard, 0.5)

    def update_dashboard(self, dt):
        if self.ctx.slot:
            self.get_room_info()
            self.get_player_info()

            if len(self.ctx.player_names) != self._last_player_count:
                self.populate_player_checkboxes()
                self._last_player_count = len(self.ctx.player_names)

    def get_room_info(self):
        if self.ctx.slot:
            self.room_info = (f"Server Address: {self.ctx.server_address}\n"
                              f"Player Count: {len(self.ctx.names)}\n"
                              f"Hint Cost: {self.ctx.server_hint_cost}\n")

    def get_player_info(self):
        if self.ctx.slot:
            self.player_info = (f"Player Names: {', '.join(self.ctx.names)}\n"
                                f"Games: {', '.join(self.ctx.games)}\n")

    def populate_player_checkboxes(self):
        """Call this function when connected to the server/room."""
        grid = self.ids.get("player_checkbox_grid")

        if grid is None:
            print(grid)
            logger.info("Player Checkbox grid doesn't exist!")
            return

        grid.clear_widgets()  # Clear old widgets from previous connections
        self.selected_players.clear()

        if not self.ctx or not hasattr(self.ctx, 'player_names'):
            return

        # Loop through players
        for slot, name in self.ctx.player_names.items():
            # Skip slots that aren't players
            if name in ["Archipelago", self.ctx.get_torture_name()]:
                continue

            # Create Player Label
            label = Label(
                text=name,
                halign='left',
                valign='middle',
                size_hint_y=None,
                height='30dp'
            )
            label.bind(size=label.setter('text_size'))

            # Create Player Checkbox
            checkbox = CheckBox(
                active=False,
                size_hint_x=None,
                width='30dp',
                size_hint_y=None,
                height='30dp'
            )

            # Bind checkbox state changes to function using a lambda
            checkbox.bind(
                active=lambda instance, is_active, player_slot=slot:
                self.on_player_toggled(player_slot, is_active)
            )

            # Add widgets to the grid
            grid.add_widget(label)
            grid.add_widget(checkbox)

    def on_player_toggled(self, slot_id: int, is_active: bool):
        """Tracks which player checkboxes are currently active."""
        player_name = self.ctx.player_names.get(slot_id, f"Slot {slot_id}")
        self.selected_players[player_name] = is_active

    def send_deathlink(self, reason: str):
        if self.ctx.slot:
            asyncio.create_task(self.ctx.send_death(reason))

    def btn_send_traps(self, amount: int | None = None):
        asyncio.create_task(self.send_traps(amount))

    async def send_traps(self, amount: int | None = None):
        amount = int(amount) if amount else None

        if not self.ctx.slot:
            return

        checked_players = [name for name, is_checked in self.selected_players.items() if is_checked]

        # Check if we're targeting anyone
        if checked_players and amount is None:
            players_chosen = checked_players

        elif checked_players and amount is not None:
            if amount > len(checked_players):
                logger.info("Amount of people to trap is more than the amount you've targeted!")
                return

            players_chosen = random.sample(checked_players, amount)
        else:
            available_players = list(self.ctx.names)
            if amount > len(available_players):
                logger.info("Amount of people to trap is more than the amount of people in the multiworld!")
                return

            players_chosen = random.sample(available_players, amount)
        traps_to_give = []

        for player in players_chosen:
            slot_num = next((k for k, v in self.ctx.player_names.items() if v == player), None)
            if not slot_num:
                continue

            # Get the game this player is playing from slot_info
            slot_data = self.ctx.slot_info.get(slot_num)
            if not slot_data:
                continue

            game_name = slot_data.game

            # Access the locally cached datapackage for their specific game
            # self.ctx.datapackage is automatically populated by the CommonClient
            if not self.ctx.datapackage:# or game_name not in self.ctx.datapackage:
                logger.info(f"DataPackage for {game_name} not loaded.")
                continue

            game_items = self.ctx.datapackage["games"][game_name]["item_name_to_id"]

            # Filter the items to find anything with "trap" in the name (case-insensitive)
            trap_names = [name for name in game_items.keys() if "trap" in name.casefold()]

            if not trap_names:
                logger.info(f"No trap items found in the DataPackage for {game_name}.")
                continue

            # Pick a random trap from their game's pool
            chosen_trap = random.choice(trap_names)
            traps_to_give.append(chosen_trap)
            #logger.info(f"Selected '{chosen_trap}' for {player}.")

        logger.info("Sending traps to...")
        for player, trap in zip(players_chosen, traps_to_give):
            json_message: list[JSONMessagePart] = [
                {"type": "color", "text": player, "color": "green"},
                {"text": " <- "},
                {"type": "color", "text": trap, "color": "salmon"}
            ]

            if self.ctx.ui is not None:
                self.ctx.ui.print_json(json_message)

        await asyncio.sleep(2)
        message = f"Cursing {', '.join(players_chosen)}!"
        asyncio.create_task(self.ctx.send_msgs([{"cmd": "Say", "text": message}]))
        await asyncio.sleep(2)

        for player, trap in zip(players_chosen, traps_to_give):
            command = f"!admin /send {player} {trap}"
            asyncio.create_task(self.ctx.send_msgs([{"cmd": "Say", "text": command}]))

    def send_private_message(self, games:list[str]|None=None, slots:list[str]|None=None, tags:list[str]|None=None, data:str=""):
        self.ctx.private_message(games, slots, tags, data)

class TortureCommandProcessor(ClientCommandProcessor):
    ctx: "TortureClientContext"

    def __init__(self, ctx: "TortureClientContext"):
        super().__init__(ctx)

    def _cmd_torture_help(self):
        logger.info("Check your browser!")
        webbrowser.open_new_tab("https://www.github.com/ElectroStarz/Torture-AP-Client/docs/help.md")


class TortureClientContext(CommonContext):
    tags = {"TextOnly", "Deathlink"}
    game = "Torture Client"
    games_present: list[str] = []
    dashboard: TortureDashboard

    server_hint_cost: int = 0
    items_handling = 0b111
    want_slot_data = False

    def __init__(self, server_address: str | None = None, password: str | None = None) -> None:
        super().__init__(server_address, password)
        self.dashboard = TortureDashboard(self)
        self.names = {}
        self.games = {}
        self.datapackage = {}

    async def server_auth(self, password_requested: bool = False):
        if password_requested and not self.password:
            await super(TortureClientContext, self).server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    def on_package(self, cmd: str, args: dict):
        if cmd == "Connected":
            self.names = {v for k, v in self.player_names.items() if v not in ["Archipelago", self.get_torture_name()]}
            self.games = {v for v in self.games_present if v not in ["Archipelago", "Torture Client"]}
            self.load_datapackage(list(self.games))

        elif cmd == "RoomInfo":
            self.games_present = args.get("games", "Disconnected")
            self.server_hint_cost = args.get("hint_cost", 0)

        elif cmd == "DataPackage":
            self.datapackage = args.get("data")


    async def disconnect(self, allow_autoreconnect: bool = False):
        self.names = {"Disconnected"}
        self.games = {"Disconnected"}
        self.server_hint_cost = -1
        await super().disconnect(allow_autoreconnect)

    def make_gui(self):
        """Overrides Archipelago's GUI builder to add custom tab."""

        kv_file_path = os.path.join(os.path.dirname(__file__), "dashboard.kv")
        Builder.load_file(kv_file_path)

        class TortureTextManager(GameManager):
            base_title = "Torture Client"

            def build(self):
                container = super().build()

                self.add_client_tab("Torture Dashboard", TortureDashboard(self.ctx))
                return container

        return TortureTextManager

    def get_torture_name(self):
        if self.slot is not None:
            slot = self.slot_info[self.slot]
            return slot.name
        else:
            return "Torture Client"

    def load_datapackage(self, games: list):
        asyncio.create_task(self.send_msgs([{"cmd": "GetDataPackage", "games": games}]))

    def private_message(self, games:list[str]|None=None, slots:list[str]|None=None, tags:list[str]|None=None, data:str=""):

        bounce_packet: dict[str, Any] = {
            "cmd": "Bounce",
            "data": data
        }

        if games:
            bounce_packet["games"] = games
        elif slots:
            ids = []
            for slot in slots:
                slot_num = next((k for k, v in self.player_names.items() if v == slot), None)
                ids.append(slot_num)
            bounce_packet["slots"] = ids
        elif tags:
            bounce_packet["tags"] = tags
        else:
            return

        # Send the packet
        asyncio.create_task(self.send_msgs([bounce_packet]))


def launch_torture_client(*args):
    Utils.init_logging("Torture Client")

    async def main(main_args):
        ctx = TortureClientContext(main_args.connect, main_args.password)
        ctx.auth = main_args.name
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="Server Loop")

        if gui_enabled:
            ctx.run_gui()
        ctx.run_cli()

        await ctx.exit_event.wait()
        ctx.server_address = None

    import colorama

    parser = get_base_parser(description="Torture Archipelago Client.")
    parser.add_argument("--name", default=None, help="Slot Name to connect as.")
    parser.add_argument("url", nargs="?", help="Archipelago connection url")

    launch_args = handle_url_arg(parser.parse_args(args))

    colorama.just_fix_windows_console()
    asyncio.run(main(launch_args))
    colorama.deinit()

if __name__ == "__main__":
    multiprocessing.freeze_support()
    launch_torture_client(*sys.argv[1:])
from kvui import GameManager
import asyncio
import logging
import multiprocessing
import os
import random
import sys
import webbrowser
from typing import Any
import re

from NetUtils import JSONMessagePart
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.properties import StringProperty, BooleanProperty
from kivy.uix.textinput import TextInput
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.checkbox import CheckBox

import Utils
from CommonClient import ClientCommandProcessor, CommonContext, get_base_parser, gui_enabled, handle_url_arg, \
    server_loop

logger = logging.getLogger("Client")

class TortureDashboard(BoxLayout):
    server_address_text = StringProperty("Server Address: Disconnected")
    password_text = StringProperty("Server Password: ******")
    room_stats_text = StringProperty("Player Count: Disconnected\nHint Cost: Disconnected")
    player_info = StringProperty("Disconnected")
    show_password = BooleanProperty(False)

    def __init__(self, ctx: "TortureAdminContext", **kwargs):
        super().__init__(**kwargs)
        self.ctx = ctx
        self.ctx.dashboard = self
        self.selected_target_players = {}
        self.selected_log_players = {}
        self._last_player_count = 0

        # Schedule the info updaters to run every 0.5 seconds
        Clock.schedule_interval(self.update_dashboard, 0.5)

        # Hook up hover detection for the password reveal-on-hover
        Window.bind(mouse_pos=self.on_mouse_pos)

    def on_mouse_pos(self, window, pos):
        if not self.get_root_window():
            return

        password_label = self.ids.get("password_label")
        if password_label:
            local_pos = password_label.to_widget(*pos)
            is_hovering = password_label.collide_point(*local_pos)

            if is_hovering != self.show_password:
                self.show_password = is_hovering
                self.update_password_display()

    def update_password_display(self):
        pwd = self.ctx.password if self.show_password else "******"
        self.password_text = f"Server Password: {pwd}"

    def update_dashboard(self, dt):
        if self.ctx.is_ready():
            self.get_room_info()
            self.get_player_info()

            if len(self.ctx.player_names) != self._last_player_count:
                self.populate_player_grid(self.ids.get("player_tg_checkbox_grid"), self.ctx.player_names, 1)
                self.populate_player_grid(self.ids.get("player_pm_checkbox_grid"), self.ctx.player_names, 2)
                self._last_player_count = len(self.ctx.player_names)

    def get_room_info(self):
        self.server_address_text = f"Server Address: {self.ctx.server_address}"
        self.update_password_display()
        self.room_stats_text = (f"Player Count: {len(self.ctx.names)}\n"
                                f"Hint Cost: {self.ctx.hint_cost}")

    def get_player_info(self):
        self.player_info = (f"Player Names: {', '.join(self.ctx.names)}\n"
                            f"Games: {', '.join(self.ctx.games)}\n")

    def populate_all_checkboxes(self):
        """Main function to call when connected to the server/room."""

        target_grid = self.ids.get("player_tg_checkbox_grid")
        pm_grid = self.ids.get("player_pm_checkbox_grid")

        # Clear selections
        self.selected_target_players.clear()

        if target_grid is not None:
            self.populate_player_grid(target_grid, self.ctx.player_names, 1)

        if target_grid is not None:
            self.populate_player_grid(pm_grid, self.ctx.player_names, 2)

    def populate_player_grid(self, grid, player_dict: dict, type: int):
        """Handles parsing dictionary data for targeting players."""
        if grid is None:
            return

        grid.clear_widgets()
        if not player_dict:
            return

        # Dictionary loops use .items() to get slot and name
        for slot, name in player_dict.items():
            if name in ["Archipelago", self.ctx.get_torture_name()]:
                continue

            if type == 1:
                callback = self.on_player_target_toggled
            else:
                callback = self.on_player_pm_toggled

                if self.ctx.custom_torture(name):
                    name = f"[color=#44FF44]{name}[/color]"
                else:
                    name = f"[color=#FF4444]{name}[/color]"

            self._create_checkbox_row(grid, display_text=name, identifier=slot, callback=callback)

    @staticmethod
    def _create_checkbox_row(grid, display_text, identifier, callback):
        """Helper function for Kivy widget generation"""
        # Create Label
        label = Label(
            text=display_text,
            halign='left',
            valign='middle',
            size_hint_y=None,
            height='30dp',
            markup=True
        )
        label.bind(size=label.setter('text_size'))

        # Create Checkbox
        checkbox = CheckBox(
            active=False,
            size_hint_x=None,
            width='30dp',
            size_hint_y=None,
            height='30dp'
        )

        # Bind checkbox state changes to the specific callback passed in
        checkbox.bind(
            active=lambda instance, is_active, passed_id=identifier:
            callback(passed_id, is_active)
        )

        # Add widgets to the grid
        grid.add_widget(label)
        grid.add_widget(checkbox)

    def on_player_target_toggled(self, slot_id: int, is_active: bool):
        """Tracks which target player checkboxes are currently active."""
        player_name = self.ctx.player_names.get(slot_id, f"Slot {slot_id}")
        self.selected_target_players[player_name] = is_active

    def on_player_pm_toggled(self, slot_id: int, is_active: bool):
        """Tracks which private message player checkboxes are currently active."""
        player_name = self.ctx.player_names.get(slot_id, f"Slot {slot_id}")
        self.selected_log_players[player_name] = is_active

    def send_deathlink(self, reason: str):
        if self.ctx.is_ready():
            asyncio.create_task(self.ctx.send_death(reason))

    def btn_send_traps(self, amount: int | None = None):
        if self.ctx.is_ready():
            checked_players = [name for name, is_checked in self.selected_target_players.items() if is_checked]
            asyncio.create_task(self.ctx.send_traps(checked_players, amount))

    def btn_log_to_client(self, data: TextInput):
        if self.ctx.is_ready():

            checked_players = [name for name, is_checked in self.selected_log_players.items() if is_checked]

            self.ctx.log_to_client(checked_players, data)

class TortureAdminCommandProcessor(ClientCommandProcessor):
    ctx: "TortureAdminContext"

    def __init__(self, ctx: "TortureAdminContext"):
        super().__init__(ctx)

    def _cmd_set_password(self, password: str):
        """Sets the torture client password"""

        if not password:
            logger.info("You must provide a password!")
            return

        if not self.ctx.slot_info or not self.ctx.slot:
            logger.info("You must be connected to a room first!")
            return

        if not self.ctx.is_ready():
            logger.info("Please enter the torture password first before using /set_password")
            return

        # Store the password
        self.ctx.torture_password = password
        logger.info(f"Torture password successfully set to: {password}")

        asyncio.create_task(self.ctx.send_msgs([{
            "cmd": "Set",
            "key": "torture_password",
            "default": [],
            "want_reply": False,
            "operations": [{"operation": "replace", "value": password}]
        }]))


    def _cmd_torture_help(self):
        """Use this command if you're struggling with how to use this"""

        logger.info("Check your browser!")
        webbrowser.open_new_tab("https://github.com/ElectroStarz/Torture-AP-Client/blob/main/docs/admin_help.md")


class TortureAdminContext(CommonContext):
    tags = {"TextOnly"}
    game = "Torture Client"
    games_present: list[str] = []
    command_processor = TortureAdminCommandProcessor

    items_handling = 0b000
    want_slot_data = False

    def __init__(self, dashboard: "TortureDashboard", server_address: str | None = None, password: str | None = None) -> None:
        super().__init__(server_address, password)
        self.dashboard = dashboard
        self.names = set()
        self.games = set()
        self.datapackage = {}
        self.player_tags = {}
        self.torture_password = None

    async def server_auth(self, password_requested: bool = False):
        if password_requested and not self.password:
            await super(TortureAdminContext, self).server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    def on_package(self, cmd: str, args: dict):
        if cmd == "Connected":
            self.names = {v for k, v in self.player_names.items() if v not in ["Archipelago", self.get_torture_name()]}
            self.games = {v for v in self.games_present if v not in ["Archipelago", "Torture Client"]}
            self.load_datapackage(list(self.games))

            # Ask the server for the password
            asyncio.create_task(self.get_torture_password())

        elif cmd == "RoomInfo":
            self.games_present = args.get("games", "Disconnected")
            print(args.get("tags", None))

        elif cmd == "DataPackage":
            self.datapackage = args.get("data")

        elif cmd == "Retrieved":
            if self.torture_password is not None:
                return

            keys_dict = args.get("keys", {})

            if "torture_password" in keys_dict:
                actual_password = keys_dict.get("torture_password")

                if actual_password is None:
                    # Password doesn't exist on the server yet
                    asyncio.create_task(self.enforce_torture_password())
                else:
                    # Password exists, force the user to enter it
                    asyncio.create_task(self.verify_torture_password(actual_password))

        elif cmd == "PrintJSON":
            if args.get("type") == "TagsChanged":
                slot = args.get("slot")
                tags = args.get("tags", [])

                self.player_tags[slot] = tags
                if self.dashboard:
                    Clock.schedule_once(lambda dt: self.dashboard.populate_all_checkboxes())

        elif cmd == "Bounced":
            data = args.get("data")
            if data is not None and data.get("action") == "status_reply":
                slot = data.get("slot")
                tags = data.get("tags", [])

                if slot is not None:
                    self.player_tags[slot] = tags
                    if self.dashboard:
                        Clock.schedule_once(lambda dt: self.dashboard.populate_all_checkboxes())

    async def enforce_torture_password(self):
        """Checks if the torture password exists, and prompts the user to create one."""

        logger.info("Please enter a password for the Torture Client")
        user_pass = await self.console_input()
        self.torture_password = user_pass

        # Send the network packet to save it to the server
        await self.send_msgs([{
            "cmd": "Set",
            "key": "torture_password",
            "default": [user_pass],
            "want_reply": False,
            "operations": [{"operation": "replace", "value": user_pass}]
        }])
        logger.info(f"Saved '{user_pass}' as password!")
        self.request_initial_sync()

    async def verify_torture_password(self, actual_password: str):
        """Prompts the user using the client's built-in console_input."""

        while True:
            logger.info("Please enter the password to gain access to the Torture Dashboard")
            user_guess = await self.console_input()

            # Check if the guess matches the real password
            if user_guess == actual_password:
                logger.info("Password accepted! Access granted.")
                self.torture_password = actual_password
                self.request_initial_sync()
                return True

            else:
                logger.info("Incorrect password. Please try again.")

    async def get_torture_password(self):
        await self.send_msgs([{
            "cmd": "Get",
            "keys": ["torture_password"]
        }])

    def get_torture_name(self):
        if self.slot is not None:
            slot = self.slot_info[self.slot]
            return slot.name
        else:
            return "Torture Client"

    def is_ready(self):
        if self.torture_password is not None:
            return True
        else:
            return False

    async def disconnect(self, allow_autoreconnect: bool = False):
        self.names = {"Disconnected"}
        self.games = {"Disconnected"}
        await super().disconnect(allow_autoreconnect)

    def make_gui(self):
        """Overrides Archipelago's GUI builder to add custom tab."""

        kv_file_path = os.path.join(os.path.dirname(__file__), "admin_dashboard.kv")
        Builder.load_file(kv_file_path)

        class TortureTextManager(GameManager):
            base_title = "Archipelago Torture Admin Client | AP Version"

            def build(self):
                container = super().build()

                self.add_client_tab("Torture Dashboard", TortureDashboard(self.ctx))
                return container

        return TortureTextManager

    def load_datapackage(self, games: list):
        asyncio.create_task(self.send_msgs([{"cmd": "GetDataPackage", "games": games}]))

    def custom_torture(self, slot_name: str):
        """Used for actions that require the Torture User Client, stops them from being sent to regular players."""

        slot_num: int = next(k for k, v in self.player_names.items() if v == slot_name)
        tags = self.player_tags.get(slot_num, [])

        if "Torture User Client" in tags:
            return True
        else:
            return False

    def request_initial_sync(self):
        """Sends a bounce packet to ask all other Torture clients for their status."""
        if self.server:
            sync_packet = {
                "cmd": "Bounce",
                "tags": ["Torture User Client"],
                "data": {"action": "request_status"}
            }
            asyncio.create_task(self.send_msgs([sync_packet]))

    async def send_traps(self, checked_players: list[str]|None = None, amount: int | None = None):
        amount = int(amount) if amount else None

        if not self.slot:
            return

        # Check if we're targeting anyone and no input has been given
        if checked_players and amount is None:
            players_chosen = checked_players

        # Targeting AND input has been give (choose random players that are selected)
        elif checked_players and amount is not None:
            if amount > len(checked_players):
                logger.info("Amount of people to trap is more than the amount you've targeted!")
                return

            players_chosen = random.sample(checked_players, amount)
        # None selected but input given, choose amount of players
        elif amount is not None and not checked_players:
            available_players = list(self.names)
            if amount > len(available_players):
                logger.info("Amount of people to trap is more than the amount of people in the multiworld!")
                return

            players_chosen = random.sample(available_players, amount)
        else:
            logger.info("Unable to send traps due to no input")
            return

        traps_to_give = []

        for player in players_chosen:
            slot_num = next((k for k, v in self.player_names.items() if v == player), None)
            if not slot_num:
                continue

            # Get the game this player is playing from slot_info
            slot_data = self.slot_info.get(slot_num)
            if not slot_data:
                continue

            game_name = slot_data.game

            # Access datapackage for their game
            if not self.datapackage:
                logger.info(f"DataPackage not loaded.")
                continue

            game_items = self.datapackage["games"][game_name]["item_name_to_id"]

            # Filter the items to find anything with "trap" in the name (case-insensitive)
            trap_names = [name for name in game_items.keys() if "trap" in name.casefold()]

            if not trap_names:
                text = f"Failed to send to {player}. No trap items found in the DataPackage for {game_name}."
                message: JSONMessagePart = {"type": "color", "text": text, "color": "red"}
                self.ui.print_json([message]) if self.ui else None
                checked_players.remove(player) if checked_players else None
                continue

            # Pick a random trap from their game's pool
            chosen_trap = random.choice(trap_names)
            traps_to_give.append(chosen_trap)

        logger.info("Sending traps to...")
        for player, trap in zip(players_chosen, traps_to_give):
            json_message: list[JSONMessagePart] = [
                {"type": "color", "text": player, "color": "green"},
                {"text": " <- "},
                {"type": "color", "text": trap, "color": "salmon"}
            ]

            if self.ui is not None:
                self.ui.print_json(json_message)

        await asyncio.sleep(2)
        text_message = f"Cursing {', '.join(players_chosen[:len(players_chosen) - 1])} and {players_chosen[-1]}!"
        asyncio.create_task(self.send_msgs([{"cmd": "Say", "text": text_message}]))
        await asyncio.sleep(2)

        for player, trap in zip(players_chosen, traps_to_give):
            command = f"!admin /send {player} {trap}"
            asyncio.create_task(self.send_msgs([{"cmd": "Say", "text": command}]))

    def log_to_client(self, slots: list[str], data: Any):
        ids: list[int] = []

        if slots:
            for slot in slots:
                if not self.custom_torture(slot):
                    logger.info(f"Unable to send message to {slot}, they do not have the Torture Client activated!")
                    continue

                slot_num = next((k for k, v in self.player_names.items() if v == slot), None)

                if slot_num is not None:
                    ids.append(int(slot_num))
        else:
            # Sends to everyone
            for name in self.names:

                if not self.custom_torture(name):
                    logger.info(f"Unable to send message to {name}, they do not have the Torture Client activated!")
                    continue

                slot_num = next((k for k, v in self.player_names.items() if v == name), None)

                if slot_num is not None:
                    ids.append(int(slot_num))



        bounce_packet = {
            "cmd": "Bounce",
            "slots": ids,
            "data": {
                "action": "pm",
                "content": self.parse_to_json_message(data.text)
            },
        }
        asyncio.create_task(self.send_msgs([bounce_packet]))

    @staticmethod
    def parse_to_json_message(input_string: str) -> list[dict]:
        # Find the {...} blocks, but only if they actually contain both 'text:' and 'color:'
        block_pattern = re.compile(r'\{(?=[^}]*text\s*:)(?=[^}]*color\s*:)([^}]+)\}')

        # This pulls out the keys and values. Using a lookahead here so it
        # doesn't accidentally split commas that belong inside the actual text
        pair_pattern = re.compile(r'(text|color)\s*:\s*(.*?)(?=\s*,\s*(?:text|color)\s*:|$)')

        message_parts = []
        last_end = 0

        for match in block_pattern.finditer(input_string):
            # Grab any normal text that showed up right before this formatted block
            plain_text = input_string[last_end:match.start()]
            if plain_text:
                message_parts.append({"text": plain_text})

            # Go through the stuff inside the braces and save the properties
            inner_content = match.group(1)
            properties = {}

            for pair_match in pair_pattern.finditer(inner_content):
                key = pair_match.group(1).lower()
                value = pair_match.group(2).strip()
                properties[key] = value

            # Build the exact JSONMessagePart dictionary format
            color_part = {
                "type": "color",
                "text": properties.get("text", ""),
                "color": properties.get("color", "").lower()
            }
            message_parts.append(color_part)

            # Keep track of where we left off
            last_end = match.end()

        # Catch any leftover normal text at the very end of the string
        remaining_text = input_string[last_end:]
        if remaining_text:
            message_parts.append({"text": remaining_text})

        return message_parts


def launch_torture_admin_client(*args):
    Utils.init_logging("Torture Admin Client")

    async def main(main_args):
        ctx = TortureAdminContext(main_args.connect, main_args.password)
        ctx.auth = main_args.name
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="Server Loop")

        if gui_enabled:
            ctx.run_gui()
        ctx.run_cli()

        await ctx.exit_event.wait()
        ctx.server_address = None

    import colorama

    parser = get_base_parser(description="Archipelago Torture Admin Client.")
    parser.add_argument("--name", default=None, help="Slot Name to connect as.")
    parser.add_argument("url", nargs="?", help="Archipelago connection url")

    launch_args = handle_url_arg(parser.parse_args(args))

    colorama.just_fix_windows_console()
    asyncio.run(main(launch_args))
    colorama.deinit()

if __name__ == "__main__":
    multiprocessing.freeze_support()
    launch_torture_admin_client(*sys.argv[1:])
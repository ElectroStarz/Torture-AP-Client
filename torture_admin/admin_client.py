from kvui import GameManager
import asyncio
import logging
import multiprocessing
import os
import random
import sys
import webbrowser
import time
from typing import Any
import string
import typing
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
from kivy.uix.dropdown import DropDown
from kivy.uix.button import Button

import Utils
from BaseClasses import MultiWorld, ItemClassification
from CommonClient import ClientCommandProcessor, CommonContext, get_base_parser, gui_enabled, handle_url_arg, \
    server_loop

logger = logging.getLogger("Client")
# Cache of game_name -> {item_name: classification} so we're not rebuilding
# a whole world object every single time someone gets sent a trap
_classification_cache: dict[str, dict[str, "ItemClassification"] | None] = {}

class TortureDashboard(BoxLayout):
    # These are all bound to widgets in dev_dashboard.kv, so updating them here
    # automatically updates what's shown on screen
    server_address_text = StringProperty("Server Address: Disconnected")
    password_text = StringProperty("Server Password: ******")
    room_stats_text = StringProperty("Player Count: Disconnected\nHint Cost: Disconnected")
    player_info = StringProperty("Disconnected")
    link_hint_text = StringProperty("Deathlink Reason")
    show_password = BooleanProperty(False)

    def __init__(self, ctx: "TortureAdminContext", **kwargs):
        super().__init__(**kwargs)
        self.ctx = ctx
        # Give the context a reference back to us so on_package() etc. can push updates in
        self.ctx.dashboard = self
        self.trigger_dropdown = Clock.create_trigger(self.create_link_dropdown)

        # Tracks the checked/unchecked state of each player's checkbox by name
        self.selected_target_players = {}
        self.selected_log_players = {}

        # Used to detect when a player joins/leaves so we know to refresh the grids
        self._last_player_count = 0

        # Used to send different links, set to None by default
        self.selected_link_type = None

        # Tracks the widgets already built for each player slot, so a single player's
        # status/tag change can update just their row instead of rebuilding the whole grid
        # (rebuilding the grid destroys every CheckBox, which resets all selections to unchecked).
        self.player_rows: dict[int, dict] = {}

        # Schedule the info updaters to run every 0.5 seconds
        Clock.schedule_interval(self.update_dashboard, 0.5)

        # Hook up hover detection for the password reveal-on-hover
        Window.bind(mouse_pos=self.on_mouse_pos)

    def on_mouse_pos(self, window, pos):
        # Only bother if we're actually mounted in a window (avoids errors on startup)
        if not self.get_root_window():
            return

        # Show the real password only while the mouse is hovering over the password label
        password_label = self.ids.get("password_label")
        if password_label:
            local_pos = password_label.to_widget(*pos)
            is_hovering = password_label.collide_point(*local_pos)

            # Only push an update if the hover state actually changed
            if is_hovering != self.show_password:
                self.show_password = is_hovering
                self.update_password_display()

    def update_password_display(self):
        """Swaps between the real password and asterisks depending on hover state"""
        pwd = self.ctx.password if self.show_password else "******"
        self.password_text = f"Server Password: {pwd}"

    def update_dashboard(self, dt):
        """Updates the information on the torture dashboard"""

        if self.ctx.is_ready():
            self.get_room_info()
            self.get_player_info()
            self.get_hint_text()

            # print(self.ctx.slot_info)
            # print(self.ctx.player_names)

            # Only rebuild the player grids when the roster actually changes size
            # (join/part), rather than on every 0.5s tick
            if len(self.ctx.player_names) != self._last_player_count:
                self.populate_all_checkboxes()
                self._last_player_count = len(self.ctx.player_names)

    def get_room_info(self):
        """Pulls the server address/password/player count/hint cost into the top info panel"""
        self.server_address_text = f"Server Address: {self.ctx.server_address}"
        self.update_password_display()
        self.room_stats_text = (f"Player Count: {len(self.ctx.names)}\n"
                                f"Hint Cost: {self.ctx.hint_cost}")

    def get_player_info(self):
        """Builds the player names / games list shown in the info panel"""
        self.player_info = (f"Player Names: {', '.join(self.ctx.names)}\n"
                            f"Games: {', '.join(self.ctx.games)}\n")

    def get_player_colour(self, name: str) -> str:
        """Calculates the player colour based on status and torture tags"""
        status_code = self.ctx.player_status.get(name, 0)

        if status_code in [5, 10, 20]:  # Active / Playing
            if self.ctx.custom_torture(name):
                return "#0096FA"  # Blue (Torture Client)
            return "#00FF00"  # Green (Regular Client)
        elif status_code == 30:
            return "#DADE00"  # Yellow (Goaled)
        else:
            return "#FF0000"  # Red (Disconnected)

    def mark_player_status(self, key: str, value: int):
        """Called whenever we get a client status back for a player - updates their status
        and refreshes just their row (see populate_all_checkboxes)"""

        # The key looks like "_read_client_status_0_<slot>", so grab the slot off the end
        slot_num = key.split("_")[-1]
        slot = self.ctx.slot_info.get(int(slot_num))

        if not slot:
            return

        name = slot.name

        # Ask everyone else for their status too, so the whole grid stays in sync
        self.ctx.request_torture_status()

        self.ctx.player_status[name] = value

        self.populate_all_checkboxes()

    def get_hint_text(self):
        """Returns the hint text for the link reason"""

        match self.selected_link_type:
            case "Deathlink": self.link_hint_text = "Deathlink Reason"
            case "Ring Link": self.link_hint_text = "Ring Link Amount"
            case _: self.link_hint_text = "Please Select a Link Type"

    def populate_all_checkboxes(self):
        """Main function to call when connected to the server/room, and any time a player's
        status/tags change. Reconciles the grids against the current player list instead of
        removing everything - new players get a row added, existing players just get their
        name colour refreshed in place"""

        target_grid = self.ids.get("player_tg_checkbox_grid")
        pm_grid = self.ids.get("player_pm_checkbox_grid")

        # Bail if the kv file hasn't finished loading these ids yet
        if target_grid is None or pm_grid is None:
            return

        current_slots = set()

        for slot, name in self.ctx.player_names.items():
            # Skip the server itself and our own torture slot
            if name in ["Archipelago", self.ctx.get_torture_name()]:
                continue

            current_slots.add(slot)

            if slot in self.player_rows:
                # Already have a row for them - just update the colour, don't touch the checkbox
                self.refresh_player_row(slot, name)
            else:
                # First time seeing this player - build them a fresh row
                self._add_player_row(slot, name, target_grid, pm_grid)

        # Clean up rows for players who are no longer present (rare, but keeps things tidy)
        for slot in list(self.player_rows.keys()):
            if slot not in current_slots:
                self._remove_player_row(slot, target_grid, pm_grid)

    def refresh_player_row(self, slot: int, name: str):
        """Updates just one player's row colour in place, leaving their checkbox state untouched."""
        row = self.player_rows.get(slot)
        if row is None:
            return

        colour = self.get_player_colour(name)
        display_name = f"[color={colour}]{name}[/color]"

        # Only touch the label text - the checkbox widget itself is left alone
        row["target_label"].text = display_name
        row["pm_label"].text = display_name
        row["name"] = name

    def _add_player_row(self, slot: int, name: str, target_grid, pm_grid):
        """Builds a new row for a player who doesn't have one yet."""
        colour = self.get_player_colour(name)
        display_name = f"[color={colour}]{name}[/color]"

        # Build one row in each grid (target players + PM players), same player different callback
        target_label, target_checkbox = self._create_checkbox_row(
            target_grid, display_text=display_name, identifier=slot, callback=self.on_player_target_toggled
        )
        pm_label, pm_checkbox = self._create_checkbox_row(
            pm_grid, display_text=display_name, identifier=slot, callback=self.on_player_pm_toggled
        )

        # Keep a handle to everything so future updates don't need to rebuild these widgets
        self.player_rows[slot] = {
            "name": name,
            "target_label": target_label,
            "target_checkbox": target_checkbox,
            "pm_label": pm_label,
            "pm_checkbox": pm_checkbox,
        }

    def _remove_player_row(self, slot: int, target_grid, pm_grid):
        """Removes a player's row and any selection state tied to their old name."""
        row = self.player_rows.pop(slot, None)
        if row is None:
            return

        # Pull their widgets out of both grids
        target_grid.remove_widget(row["target_label"])
        target_grid.remove_widget(row["target_checkbox"])
        pm_grid.remove_widget(row["pm_label"])
        pm_grid.remove_widget(row["pm_checkbox"])

        # Don't leave a stale entry sitting in the selection dicts for a player who left
        self.selected_target_players.pop(row["name"], None)
        self.selected_log_players.pop(row["name"], None)

    @staticmethod
    def _create_checkbox_row(grid, display_text, identifier, callback):
        """Helper function for Kivy widget generation. Returns (label, checkbox) so the caller
        can keep a handle on them for later in-place updates."""
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

        return label, checkbox

    def clear_all_rows(self):
        """Wipes every player row out of both grids and resets all selection state.
        Called when we disconnect, so a stale roster from the old room doesn't linger."""
        target_grid = self.ids.get("player_tg_checkbox_grid")
        pm_grid = self.ids.get("player_pm_checkbox_grid")

        if target_grid is not None:
            target_grid.clear_widgets()
        if pm_grid is not None:
            pm_grid.clear_widgets()

        self.player_rows.clear()
        self.selected_target_players.clear()
        self.selected_log_players.clear()

        # Force the next connect to rebuild the grids
        self._last_player_count = 0

    def create_link_dropdown(self, dt=None):
        """Builds the Deathlink / Ring Link dropdown selector once the kv file has loaded"""
        class LinkDropDown(DropDown):
            pass

        dropdown = LinkDropDown()
        mainbutton = Button(text='Select Link Type', size_hint=(1, 1))
        mainbutton.bind(on_release=dropdown.open)

        # Helper function to save the selected value and update the button label
        def on_type_selected(instance, value):
            mainbutton.text = value.title()
            self.selected_link_type = value

        dropdown.bind(on_select=on_type_selected)

        # Swap the placeholder widget in the kv layout for our actual dropdown button
        link_trap_widget = self.ids.get("link_trap")
        if link_trap_widget:
            link_trap_widget.clear_widgets()
            link_trap_widget.add_widget(mainbutton)

    def on_player_target_toggled(self, slot_id: int, is_active: bool):
        """Tracks which target player checkboxes are currently active."""
        player_name = self.ctx.player_names.get(slot_id, f"Slot {slot_id}")
        self.selected_target_players[player_name] = is_active

    def on_player_pm_toggled(self, slot_id: int, is_active: bool):
        """Tracks which private message player checkboxes are currently active."""
        player_name = self.ctx.player_names.get(slot_id, f"Slot {slot_id}")
        self.selected_log_players[player_name] = is_active

    def send_link(self, text: str):
        """Fired by the Send Link button - sends either a Deathlink or a Ring Link"""
        if self.ctx.is_ready():

            if self.selected_link_type == "Deathlink":
                asyncio.create_task(self.ctx.send_death(text))
            elif self.selected_link_type == "Ring Link":
                # Ring Link amount has to actually be a number, so validate before sending
                if text in string.digits:
                    logger.info("Sending Ring Link...")

                    asyncio.create_task(self.ctx.send_msgs([{
                        "cmd": "Bounce",
                        "tags": "RingLink",
                        "data":
                            {"time": time.time(),
                             "source": self.ctx.instance_id,
                             "amount": int(text)}
                    }]))

                else:
                    logger.info(f"'{text}' isn't a valid number!")
            else:
                logger.info("Please select a Link Type!")

    def btn_send_traps(self, amount: int | None = None):
        """Fired by the Send Traps button"""
        if self.ctx.is_ready():
            # Only pass along the players whose checkbox is actually ticked
            checked_players = [name for name, is_checked in self.selected_target_players.items() if is_checked]
            asyncio.create_task(self.ctx.send_traps(checked_players, amount))

    def btn_log_to_client(self, data: TextInput):
        """Fired by the Log to Clients button"""
        if self.ctx.is_ready():

            checked_players = [name for name, is_checked in self.selected_log_players.items() if is_checked]

            self.ctx.log_to_client(checked_players, data.text)

class TortureAdminCommandProcessor(ClientCommandProcessor):
    ctx: "TortureAdminContext"

    def __init__(self, ctx: "TortureAdminContext"):
        super().__init__(ctx)

    def _cmd_set_password(self, password: str):
        """Sets the torture client password"""

        if not password:
            logger.info("You must provide a password")
            return

        if not self.ctx.slot_info or not self.ctx.slot:
            logger.info("You must be connected to a room first")
            return

        if not self.ctx.is_ready():
            logger.info("Please enter the torture password first before using /set_password")
            return

        # Store the password
        self.ctx.torture_password = password
        logger.info(f"Torture password successfully set to: {password}")

        # Push the new password up to the server so it's saved for next time
        asyncio.create_task(self.ctx.send_msgs([{
            "cmd": "Set",
            "key": "torture_password",
            "default": [],
            "want_reply": False,
            "operations": [{"operation": "replace", "value": password}]
        }]))

    def _cmd_trap_fallback(self):
        """Toggles the fallback for trap sending (Off by default)

        Some worlds may not have items with ItemClassification.trap,
        the fallback is to search for items with 'trap' in them.

        This may not be 100% accurate, enable at your own discretion"""

        self.ctx.trap_fallback = not self.ctx.trap_fallback

        if self.ctx.trap_fallback:
            logger.info("Trap Fallback Enabled")
        else:
            logger.info("Trap Fallback Disabled")

    def _cmd_torture_doc(self):
        """Use this command if you're struggling with how to use the Admin Client"""

        logger.info("Check your browser!")
        webbrowser.open_new_tab("https://github.com/ElectroStarz/Torture-AP-Client/blob/main/docs/admin_help.md")

    def _cmd_torture_overview(self):
        """Displays an overview of the Torture Dashboard"""
        logger.info(
            f"Player & Server Information: Displays select information about the multiworld\n"
            f"Torture Players: Send different types of links as well as traps to players\n"
            f"Target Players: Target Players for trap sending\n"
            f"Log to Client: Log a message to clients (Works with blue names)\n"
            f"Trap Fallback: {self.ctx.trap_fallback}"
        )

class TortureAdminContext(CommonContext):
    dashboard: TortureDashboard
    tags = {"TextOnly", "Deathlink", "RingLink"}
    game = "Torture Client"
    games_present: list[str] = []
    command_processor = TortureAdminCommandProcessor

    # We don't need actual item handling for this client, it's admin-only
    items_handling = 0b000
    want_slot_data = False

    def __init__(self, server_address: str | None = None, password: str | None = None) -> None:
        super().__init__(server_address, password)

        # Gets set for real once TortureDashboard is created (see TortureDashboard.__init__).
        # Stays None if the GUI never spins up (e.g. headless/CLI mode), so every access to
        # this needs to check for None first.
        self.dashboard: TortureDashboard | None = None

        self.names = set()
        self.games = set()
        self.datapackage = {}
        self.player_tags = {}
        self.player_status = {}
        self.torture_password = None
        self.trap_fallback = False

    async def server_auth(self, password_requested: bool = False):
        if password_requested and not self.password:
            await super(TortureAdminContext, self).server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    def on_package(self, cmd: str, args: dict):
        # Used as a unique id for this run of the client, mainly for Ring Link sync
        if not hasattr(self, "instance_id"):
            self.instance_id = time.time()

        if cmd == "Connected":
            # Build the display sets of player names / games, filtering out the server and ourselves
            self.names = {v for k, v in self.player_names.items() if v not in ["Archipelago", self.get_torture_name()]}
            self.games = {v for v in self.games_present if v not in ["Archipelago", "Torture Client"]}
            self.load_datapackage(list(self.games))

            if self.dashboard:
                self.dashboard.trigger_dropdown()

            # Ask the server for the password
            asyncio.create_task(self.get_torture_password())


        elif cmd == "RoomInfo":
            self.games_present = args.get("games", "Disconnected")
            #print(args.get("tags", None))

        elif cmd == "DataPackage":
            self.datapackage = args.get("data")

        elif cmd == "Retrieved":

            keys_dict = args.get("keys", {})

            if "torture_password" in keys_dict and self.torture_password is None:
                actual_password = keys_dict.get("torture_password")

                if actual_password is None:
                    # Password doesn't exist on the server yet
                    asyncio.create_task(self.enforce_torture_password())
                else:
                    # Password exists, force the user to enter it
                    asyncio.create_task(self.verify_torture_password(actual_password))

            elif any(key.startswith("_read_client_status_0_") for key in keys_dict):
                if self.dashboard:
                    for key, value in keys_dict.items():
                        self.dashboard.mark_player_status(key, value)

        elif cmd == "PrintJSON":
            type = args.get("type")
            slot = args.get("slot")

            if type == "TagsChanged":
                tags = args.get("tags", [])

                self.player_tags[slot] = tags
                #print(self.player_tags)
                if self.dashboard:
                    self.dashboard.populate_all_checkboxes()

            elif type in ["Join", "Part"]:
                # Don't bother requesting our own status
                if not self.slot_concerns_self(slot):
                    self.request_client_status(slot)

        elif cmd == "Bounced":
            data = args.get("data", None)
            if data is not None:
                if data.get("action") == "status_reply":
                    slot = data.get("slot")
                    tags = data.get("tags", [])

                    if slot is not None:
                        self.player_tags[slot] = tags
                        if self.dashboard:
                            # Defer to next frame so we're not mutating widgets mid-packet-handling
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
        self.log_colour(f"Saved '{user_pass}' as password!", "green")
        self.request_torture_status()

        # Also ask everyone currently in the room for their status right away
        for slot in self.player_names:
            if self.slot_concerns_self(slot):
                self.request_client_status(slot)

    async def verify_torture_password(self, actual_password: str):
        """Prompts the user using the client's built-in console_input."""

        while True:
            logger.info("Please enter the password to gain access to the Torture Dashboard")
            user_guess = await self.console_input()

            # Check if the guess matches the real password
            if user_guess == actual_password:
                self.log_colour("Password accepted! Access granted.", "green")
                self.torture_password = actual_password
                self.request_torture_status()

                for slot in self.player_names:
                    if not self.slot_concerns_self(slot):
                        self.request_client_status(slot)
                return True

            else:
                self.log_colour("Incorrect password. Please try again.", "salmon")

    async def get_torture_password(self):
        """Asks the server if a torture password has already been set for this room"""
        await self.send_msgs([{
            "cmd": "Get",
            "keys": ["torture_password"]
        }])

    def get_torture_name(self):
        """Returns our own slot name, or a fallback if we're not connected yet"""
        if self.slot is not None:
            slot = self.slot_info[self.slot]
            return slot.name
        else:
            return "Torture Client"

    def is_ready(self):
        """We're only 'ready' once the torture password has been entered/verified"""
        if self.torture_password is not None:
            return True
        else:
            return False

    async def disconnect(self, allow_autoreconnect: bool = False):
        # Reset everything back to a disconnected state so the dashboard shows it clearly
        self.names = {"Disconnected"}
        self.games = {"Disconnected"}
        self.player_status.clear()
        self.torture_password = None

        # Wipe the player checkboxes too, otherwise the old room's players stick around on screen
        if self.dashboard:
            self.dashboard.clear_all_rows()

        await super().disconnect(allow_autoreconnect)

    def make_gui(self):
        """Overrides Archipelago's GUI builder to add custom tab."""

        # Load our custom kv layout alongside AP's default one
        kv_file_path = os.path.join(os.path.dirname(__file__), "admin_dashboard.kv")
        Builder.load_file(kv_file_path)

        class TortureTextManager(GameManager):
            base_title = "Archipelago Torture Admin Client | AP Version"

            def build(self):
                container = super().build()

                # This is what actually creates the TortureDashboard and wires up self.ctx.dashboard
                self.add_client_tab("Torture Dashboard", TortureDashboard(self.ctx))
                return container

        return TortureTextManager

    def log_colour(self, text: str, color: str):
        """Logs a coloured message to the client"""
        if self.ui is not None:
            message: JSONMessagePart = {"type": "color", "text": text, "color": color.casefold()}
            self.ui.print_json([message])

    def load_datapackage(self, games: list):
        """Requests the datapackage for the given games"""
        asyncio.create_task(self.send_msgs([{"cmd": "GetDataPackage", "games": games}]))

    def custom_torture(self, slot_name: str):
        """Used for actions that require the Torture User Client, stops them from being sent to regular players."""

        slot_num: int = next(k for k, v in self.player_names.items() if v == slot_name)
        tags = self.player_tags.get(slot_num, [])

        if "Torture User Client" in tags:
            return True
        else:
            return False

    def request_torture_status(self):
        """Sends a bounce packet to ask all other Torture clients for their status."""
        if self.server:
            sync_packet = {
                "cmd": "Bounce",
                "tags": ["Torture User Client"],
                "data": {"action": "request_status"}
            }
            asyncio.create_task(self.send_msgs([sync_packet]))

    def request_client_status(self, slot):
        """Sends a Get packet to the server for the slot's ClientStatus"""

        packet = {
            "cmd": "Get",
            "keys": [f"_read_client_status_0_{slot}"],
        }

        asyncio.create_task(self.send_msgs([packet]))

    def _build_world_classifications(self, game_name: str) -> dict[str, ItemClassification] | None:
        """
        Does a small generation of the world in the client so we can tell an
        item's classification. Returns None to fall back to item name method
        """
        try:
            from worlds.AutoWorld import AutoWorldRegister
        except ImportError:
            self.log_colour("worlds.AutoWorld not importable; falling back to name matching.", "salmon")
            return None

        # Registry of every APWorld that's installed locally.
        # If the game isn't in here we have no way to know real classifications.
        world_type = AutoWorldRegister.world_types.get(game_name)
        if world_type is None:
            self.log_colour(f"No APWorld installed locally for '{game_name}'; falling back to name matching.", "salmon")
            return None

        try:
            # Fake a barebones multiworld with just 1 player so we have
            # somewhere to attach the world object to. We're not actually generating
            # anything here, just enough scaffolding to call create_item.
            mw = MultiWorld(1)
            mw.game[1] = game_name
            mw.player_name[1] = "Player1"

            try:
                mw.set_seed()
            except Exception as e:
                self.exception_begone(e)
                pass  # some AP versions don't need/expose this, don't care if it fails

            world = world_type(mw, 1)
            mw.worlds[1] = world

            try:
                type_hints: Any = world_type.options_dataclass.type_hints

                world.options = world_type.options_dataclass(**{
                    opt_name: opt_cls.from_any(opt_cls.default)
                    for opt_name, opt_cls in type_hints.items()
                })
            except Exception as e:
                logger.debug(f"Could not set default options for {game_name}: {e}")

            # Now the actual point of all this - ask the real world code what
            # classification every single item name actually has
            classifications: dict[str, ItemClassification] = {}
            for item_name in world.item_name_to_id:
                try:
                    classifications[item_name] = world.create_item(item_name).classification
                except Exception as e:
                    self.exception_begone(e)
                    # some items need generation state we don't have (progressive
                    # items, option-dependent stuff etc), just skip those
                    continue

            if not classifications:
                return None

            return classifications

        except Exception as e:
            # Catch-all so one broken/incompatible APWorld doesn't take down
            # the whole command for every other game
            logger.debug(f"Failed to build a local world for '{game_name}': {e}")
            return None

    def get_trap_item_names(self, game_name: str, available_item_names: list[str]) -> list[str]:
        """
        Filters a list of item names down to just the ones that are have
        ItemClassification.trap for this game. Falls back to name checking
        """
        # Only build this once per game and reuse it after that
        if game_name not in _classification_cache:
            _classification_cache[game_name] = self._build_world_classifications(game_name)

        table = _classification_cache[game_name]

        if table is None and not self.trap_fallback:
            # No item table & trap fall back is set to false, return nothing
            return []

        elif table is None and self.trap_fallback:
            # Couldn't get real data for this game, fall back to old behaviour
            # so the command still works even if it's less accurate
            return [name for name in available_item_names if "trap" in name.casefold()]

        else:
            # & instead of == because ItemClassification is a flag enum - items can
            # be trap + something else combined, so we just check the bit is set
            return [
                name for name in available_item_names
                if table.get(name, ItemClassification.filler) & ItemClassification.trap
            ]

    async def send_traps(self, checked_players: list[str] | None = None, amount: int | None = None):
        """Sends traps to random / selected people
        Does not require the User Client"""

        amount = amount if amount and amount > 0 else None

        if not self.slot:
            return

        if not checked_players and amount is None:
            self.log_colour("Amount of people to trap is zero!", "salmon")
            return

        # Check if we're targeting anyone and no input has been given
        if checked_players and amount is None:
            players_chosen = checked_players

        # Targeting AND input has been give (choose random players that are selected)
        elif checked_players and amount is not None:
            if amount > len(checked_players):
                self.log_colour("Amount of people to trap is more than the amount you've targeted!", "salmon")
                return

            players_chosen = random.sample(checked_players, amount)
        # None selected but input given, choose amount of players
        elif amount is not None and not checked_players:
            available_players = list(self.names)
            if amount > len(available_players):
                self.log_colour("Amount of people to trap is more than the amount of people in the multiworld!",
                                "salmon")
                return

            players_chosen = random.sample(available_players, amount)
        else:
            self.log_colour("Unable to send traps due to no input", "salmon")
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
                self.log_colour(f"DataPackage not loaded.", "salmon")
                continue

            game_items = self.datapackage["games"][game_name]["item_name_to_id"]

            trap_names = self.get_trap_item_names(game_name, list(game_items.keys()))

            if not trap_names:
                self.log_colour(f"Failed to send to {player}. No trap items found for {game_name}.", "salmon")
                checked_players.remove(player) if checked_players else None
                continue

            # Pick a random trap from their game's actual trap pool
            chosen_trap = random.choice(trap_names)
            traps_to_give.append(chosen_trap)

        logger.info("Sending traps to...")
        for player, trap in zip(players_chosen, traps_to_give):
            json_message: list = [
                {"type": "color", "text": player, "color": "green"},
                {"text": " <- "},
                {"type": "color", "text": trap, "color": "salmon"}
            ]

            if self.ui is not None:
                self.ui.print_json(json_message)

        # Small pause before the traps actually go out
        await asyncio.sleep(2)
        if len(players_chosen) == 1:
            player_message = players_chosen[0]
        else:
            player_message = f"{', '.join(players_chosen[:len(players_chosen) - 1])} and {players_chosen[-1]}"
        text_message = f"Cursing {player_message}!"
        asyncio.create_task(self.send_msgs([{"cmd": "Say", "text": text_message}]))
        await asyncio.sleep(2)

        # Send each trap via the server's admin command
        for player, trap in zip(players_chosen, traps_to_give):
            asyncio.create_task(self.send_msgs([{"cmd": "Say", "text": f"!admin /send {player} {trap}"}]))

    def log_to_client(self, slots: list[str], data: str):
        """Sends a bounce packet to the selected / everyone it can where the data gets logged on the user's client
        Requires User Client"""

        ids: list[int] = []

        if slots:
            to_loop = slots
        else:
            to_loop = self.names

        for slot in to_loop:
            if not self.custom_torture(slot):
                self.log_colour(f"Unable to send message to {slot}, they do not have the Torture Client activated!", "salmon")
                continue

            slot_num = next((k for k, v in self.player_names.items() if v == slot), None)

            if slot_num is not None:
                ids.append(int(slot_num))


        bounce_packet = {
            "cmd": "Bounce",
            "slots": ids,
            "data": {
                "action": "pm",
                "content": self.parse_to_json_message(data)
            },
        }
        asyncio.create_task(self.send_msgs([bounce_packet]))

    @staticmethod
    def parse_to_json_message(input_string: str) -> list[dict]:
        """Used to find curly braces for coloured text and formats it accordingly"""

        # Find the {...} blocks, but only if they actually contain both 'text:' and 'colour:|color:'
        block_pattern = re.compile(r'\{(?=[^}]*text\s*:)(?=[^}]*(color|colour)\s*:)([^}]+)')

        # This pulls out the keys and values. Using a lookahead here so it
        # doesn't accidentally split commas that belong inside the actual text
        pair_pattern = re.compile(r'(text|color|colour)\s*:\s*(.*?)(?=\s*,\s*(?:text|color|colour)\s*:|$)\}')

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

            # Build the JSONMessagePart
            color_part = {
                "type": "color",
                "text": properties.get("text", ""),
                "color": properties.get("color", "").casefold()
            }
            message_parts.append(color_part)

            # Keep track of where we left off
            last_end = match.end()

        # Catch any leftover normal text at the very end of the string
        remaining_text = input_string[last_end:]
        if remaining_text:
            message_parts.append({"text": remaining_text})

        return message_parts

    def exception_begone(self, text):
        """Literally does nothing with an exception, just
        to get rid of the too broad exception error"""
        pass


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
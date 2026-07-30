# def populate_game_grid(self, grid, game_set: set):
#     """Handles parsing set/list data for games."""
#     if grid is None:
#         return
#
#     grid.clear_widgets()
#     if not game_set:
#         return
#
#     # Sets/Lists loop directly through the names
#     for game_name in game_set:
#         if game_name in ["Archipelago", "Torture Client"]:
#             continue
#
#
#         self._create_checkbox_row(grid, display_text=game_name, identifier=game_name, callback=self.on_game_toggled)

# def on_player_pm_toggled(self, slot_id: int, is_active: bool):
#     """Tracks which private message player checkboxes are currently active."""
#     player_name = self.ctx.player_names.get(slot_id, f"Slot {slot_id}")
#     self.selected_pm_players[player_name] = is_active

# def on_game_pm_toggled(self, slot_id: int, is_active: bool):
#     """Tracks which private message player checkboxes are currently active."""
#     slot_data = self.slot_info.get(slot_id)
#     game = slot_data.game
#
#     self.selected_pm_games[game] = is_active
#


# def btn_private_message(self, data: TextInput):
#     checked_games = [name for name, is_checked in self.selected_pm_games.items() if is_checked]
#     checked_players = [name for name, is_checked in self.selected_pm_players.items() if is_checked]
#
#     self.ctx.private_message(checked_games, checked_players, data)


# Doesn't work, might use for something else later
# def private_message(self, games:list[str]|None=None, slots:list[str]|None=None, data: TextInput|Any = Any):
#
#     bounce_packet: dict[str, Any] = {
#         "cmd": "Bounce",
#         "data": {
#             {"cmd": "Say", "text": data.text}
#         }
#     }
#
#     if games:
#         bounce_packet["games"] = games
#     if slots:
#         ids = []
#         for slot in slots:
#             slot_num = next((k for k, v in self.player_names.items() if v == slot), None)
#             ids.append(slot_num)
#         bounce_packet["slots"] = ids
#     # elif tags:
#     #     bounce_packet["tags"] = tags
#     else:
#         return
#
#     # Send the packet
#     logger.info(f"Sending to {slots} with id {ids}\n"
#                 f"Bounce packet {bounce_packet}")
#     asyncio.create_task(self.send_msgs([bounce_packet]))
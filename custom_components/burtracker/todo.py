"""Expose BurTracker's authoritative shopping list as a native HA to-do."""
from homeassistant.components.todo import (
    TodoItem, TodoItemStatus, TodoListEntity, TodoListEntityFeature,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([BurTrackerShoppingList(entry)])


class BurTrackerShoppingList(TodoListEntity):
    _attr_name = "BurTracker Shopping"
    _attr_should_poll = False
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(self, entry):
        self._household = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_shopping"

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(
            self.hass, self._household.signal, self.async_write_ha_state
        ))

    @property
    def todo_items(self):
        return [
            TodoItem(
                uid=item["uid"], summary=item["summary"],
                status=TodoItemStatus(item["status"]),
                description=(
                    f"Barcode: {item['barcode']} | Retailer match: unresolved"
                    if item.get("barcode") else None
                ),
            )
            for item in self._household.model.items
        ]

    async def _mutate(self, method, *args):
        try:
            return await self._household.async_mutate(method, *args)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_create_todo_item(self, item):
        await self._mutate("create", item.summary, dt_util.utcnow().isoformat())

    async def async_update_todo_item(self, item):
        await self._mutate(
            "update", item.uid, item.summary,
            item.status.value if item.status is not None else None,
            dt_util.utcnow().isoformat(),
        )

    async def async_delete_todo_items(self, uids):
        await self._mutate("delete", uids)

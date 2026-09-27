"""Native editable entities used to collect one meal's feedback."""
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.text import TextEntity, TextMode

FEEDBACK_METRICS = ["enjoyment", "difficulty", "portions", "approval", "cost", "other"]


class FeedbackMetric(SelectEntity):
    """Feedback dimension selector."""

    _attr_has_entity_name = False
    _attr_name = "BurTracker Feedback Metric"
    _attr_icon = "mdi:comment-check"
    _attr_options = FEEDBACK_METRICS
    _attr_should_poll = False

    def __init__(self, entry):
        self._attr_unique_id = f"{entry.entry_id}_feedback_metric"
        self._attr_current_option = "enjoyment"

    async def async_select_option(self, option):
        self._attr_current_option = option
        self.async_write_ha_state()


class FeedbackScore(NumberEntity):
    """1-5 score for the selected feedback dimension."""

    _attr_has_entity_name = False
    _attr_name = "BurTracker Feedback Score"
    _attr_icon = "mdi:star"
    _attr_native_min_value = 1
    _attr_native_max_value = 5
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_should_poll = False

    def __init__(self, entry):
        self._attr_unique_id = f"{entry.entry_id}_feedback_score"
        self._attr_native_value = 3

    async def async_set_native_value(self, value):
        self._attr_native_value = int(value)
        self.async_write_ha_state()


class FeedbackComment(TextEntity):
    """Optional free-text comment for the selected metric."""

    _attr_has_entity_name = False
    _attr_name = "BurTracker Feedback Comment"
    _attr_icon = "mdi:comment-text-outline"
    _attr_mode = TextMode.TEXT
    _attr_native_min = 0
    _attr_native_max = 2000
    _attr_should_poll = False

    def __init__(self, entry):
        self._attr_unique_id = f"{entry.entry_id}_feedback_comment"
        self._attr_native_value = ""

    async def async_set_value(self, value):
        self._attr_native_value = value[:2000]
        self.async_write_ha_state()


def select_entities(entry):
    return [FeedbackMetric(entry)]


def number_entities(entry):
    return [FeedbackScore(entry)]


def text_entities(entry):
    return [FeedbackComment(entry)]

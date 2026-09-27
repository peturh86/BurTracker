"""Expose planned dinners as a native Home Assistant calendar."""
from datetime import datetime, time, timedelta
from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.util import dt as dt_util
from . import meals

async def async_setup_entry(hass, entry, async_add_entities):
 async_add_entities([MealCalendar(entry)])

class MealCalendar(CalendarEntity):
 _attr_name="BurTracker Meals"
 _attr_has_entity_name=True
 def __init__(self,entry):
  self._entry=entry
  self._attr_unique_id=f"{entry.entry_id}_meals"
  self._event=None
 async def async_update(self):
  rows=meals.meals()
  today=dt_util.now().date().isoformat()
  row=next((r for r in rows if r['day']==today and r['status']=='planned'),None)
  self._event=self._as_event(row) if row else None
 async def async_get_events(self,hass,start_date,end_date):
  rows=meals.meals(start_date.date().isoformat(),(end_date-timedelta(microseconds=1)).date().isoformat())
  return [self._as_event(r) for r in rows if r['status']=='planned']
 @property
 def event(self):return self._event
 @staticmethod
 def _as_event(row):
  day=datetime.fromisoformat(row['day']).date()
  start=dt_util.as_local(datetime.combine(day,time(17,30)))
  end=start+timedelta(hours=1)
  description='\n'.join(x for x in [row.get('ingredients') or '',row.get('instructions') or '',row.get('notes') or ''] if x)
  return CalendarEvent(start=start,end=end,summary=row['title'],description=description)

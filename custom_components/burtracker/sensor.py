"""Expose planned dinners and explicit waste reports in Home Assistant."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from . import meals

async def async_setup_entry(hass, entry, async_add_entities):
 async_add_entities([SpoilageReports(entry), PantrySummary(entry), TodayMeal(entry)])

class _MealSensor(SensorEntity):
 _attr_has_entity_name=True
 _attr_should_poll=True
 def __init__(self,entry,suffix):self._attr_unique_id=f"{entry.entry_id}_{suffix}"

class SpoilageReports(_MealSensor):
 _attr_name="BurTracker Spoilage Reports"
 _attr_icon="mdi:food-off"
 def __init__(self,entry):
  super().__init__(entry,'spoilage');self.household=entry.runtime_data
 async def async_added_to_hass(self):
  await super().async_added_to_hass()
  self.async_on_remove(async_dispatcher_connect(self.hass,self.household.signal,self.async_write_ha_state))
 @property
 def native_value(self):return len(self.household.model.spoiled)
 @property
 def extra_state_attributes(self):
  reports=self.household.model.spoiled
  return {'last_report':dict(reports[-1]) if reports else None}

class PantrySummary(_MealSensor):
 _attr_name="Pantry Barcode Observations"
 _attr_icon="mdi:barcode-scan"
 def __init__(self,entry):super().__init__(entry,'pantry_observations')
 @property
 def native_value(self):return len(meals.recent_pantry())
 @property
 def extra_state_attributes(self):return {'items':meals.recent_pantry()}

class TodayMeal(_MealSensor):
 _attr_name="Today's Meal"
 _attr_icon="mdi:food"
 def __init__(self,entry):super().__init__(entry,'today_meal')
 def _row(self):
  from datetime import date
  return next((r for r in meals.meals() if r['day']==date.today().isoformat()),None)
 @property
 def native_value(self):
  row=self._row()
  if not row:return 'No meal planned'
  if row['status']=='planned':return row['title']
  return {'cooked':f"Cooked: {row['title']}",'not_home':'Not home','ate_out':'Eating out','cancelled':'Meal cancelled'}.get(row['status'],row['title'])
 @property
 def extra_state_attributes(self):
  row=self._row() or {}
  return {k:row.get(k) for k in ('day','recipe_name','portions','ingredients','instructions','status','cost_isk')}

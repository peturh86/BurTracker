"""Expose planned dinners and explicit waste reports in Home Assistant."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from . import meals
from .meal_rerun_entities import MealRerunStatus

async def async_setup_entry(hass, entry, async_add_entities):
 async_add_entities([SpoilageReports(entry), PantrySummary(entry), TodayMeal(entry), TomorrowMeal(entry), MealRerunStatus(entry)])

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
 day_offset=0
 suffix='today_meal'
 def __init__(self,entry):super().__init__(entry,self.suffix)
 def _row(self):
  from datetime import date,timedelta
  target=(date.today()+timedelta(days=self.day_offset)).isoformat()
  return next((r for r in meals.meals(target,target)),None)
 @property
 def native_value(self):
  row=self._row()
  if not row:return 'No meal planned'
  if row['status']=='planned':return row['title']
  return {'cooked':f"Cooked: {row['title']}",'not_home':'Not home','ate_out':'Eating out','cancelled':'Meal cancelled'}.get(row['status'],row['title'])
 @property
 def extra_state_attributes(self):
  row=self._row() or {}
  attrs={k:row.get(k) for k in ('day','recipe_name','portions','ingredients','instructions','status','cost_isk','notes','source_url')}
  if row.get('day'):
   items=meals.meal_shopping_items(row['day'])
   attrs['shopping_items']=items
   attrs['cost_per_portion_isk']=round(row['cost_isk']/row['portions'],2) if row.get('cost_isk') is not None and row.get('portions') else None
   attrs['price_observed_at']=max((x['observed_at'] for x in items),default=None)
  else:
   attrs.update(shopping_items=[],cost_per_portion_isk=None,price_observed_at=None)
  return attrs

class TomorrowMeal(TodayMeal):
 _attr_name="Tomorrow's Meal"
 day_offset=1
 suffix='tomorrow_meal'

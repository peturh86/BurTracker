"""Home Assistant REST bridge for BurTracker meal records."""
from datetime import date,datetime,time,timedelta
from http import HTTPStatus
import asyncio
import hmac
import ipaddress
import json
import os
from pathlib import Path
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.const import KEY_AUTHENTICATED,KEY_HASS
from homeassistant.util import dt as dt_util
from .const import DOMAIN
from . import meals as meal_store
from .meals import api_call
from .retailer import LookupFailure

class MealPlannerView(HomeAssistantView):
 url = "/api/burtracker/meals/{action}"
 name = "api:burtracker:meals"
 requires_auth = False

 @staticmethod
 async def _authorized(request):
  if request.get(KEY_AUTHENTICATED,False):return True
  token_file=os.environ.get('BURTRACKER_AGENT_TOKEN_FILE')
  remote=request.remote
  try:
   if not token_file or not remote or not ipaddress.ip_address(remote).is_loopback:return False
   expected=(await asyncio.to_thread(Path(token_file).read_text,encoding='utf-8')).strip()
  except (OSError,ValueError):return False
  supplied=request.headers.get('X-BurTracker-Agent','')
  return bool(expected and supplied) and hmac.compare_digest(expected,supplied)

 async def get(self, request, action):
  if not await self._authorized(request):return web.json_response({'error':'unauthorized'},status=HTTPStatus.UNAUTHORIZED)
  try:
   args={k:request.query[k] for k in request.query}
   if action=='calendar_events':
    hass=request.app[KEY_HASS]
    start=date.fromisoformat(args['start'])
    end=date.fromisoformat(args['end'])
    if end<start or (end-start).days>90:raise ValueError('calendar range must be ordered and at most 90 days')
    calendars=sorted(s.entity_id for s in hass.states.async_all('calendar') if s.entity_id!='calendar.burtracker_meals')
    if not calendars:return web.json_response({'calendars':[],'events':{},'note':'No external Home Assistant calendar entities are configured.'})
    begin=dt_util.as_local(datetime.combine(start,time.min))
    finish=dt_util.as_local(datetime.combine(end+timedelta(days=1),time.min))
    response=await hass.services.async_call('calendar','get_events',{
     'entity_id':calendars,'start_date_time':begin.isoformat(),'end_date_time':finish.isoformat()
    },blocking=True,return_response=True)
    return self.json({'calendars':calendars,'events':response or {}})
   return web.json_response(api_call(action,**args))
  except (ValueError,KeyError) as err:
   return web.json_response({'error':str(err)},status=HTTPStatus.BAD_REQUEST)
  except LookupError as err:
   return web.json_response({'error':str(err)},status=HTTPStatus.NOT_FOUND)
  except LookupFailure as err:
   status=HTTPStatus.TOO_MANY_REQUESTS if err.status=='rate_limited' else HTTPStatus.BAD_GATEWAY
   return web.json_response({'error':err.status},status=status)
  except TimeoutError:
   return web.json_response({'error':'kronan_timeout'},status=HTTPStatus.GATEWAY_TIMEOUT)
  except Exception:
   return web.json_response({'error':'internal_error'},status=HTTPStatus.INTERNAL_SERVER_ERROR)

 async def post(self, request, action):
  if not await self._authorized(request):return web.json_response({'error':'unauthorized'},status=HTTPStatus.UNAUTHORIZED)
  try:
   args=await request.json()
   if not isinstance(args,dict):raise ValueError('JSON object required')
   if action in {'kronan_search','kronan_stores','kronan_recipe_search','kronan_recipe','quote_kronan_recipe','quote_generated_meal','save_meal_quote'}:
    hass=request.app[KEY_HASS]
    entries=hass.config_entries.async_entries(DOMAIN)
    households=[getattr(entry,'runtime_data',None) for entry in entries]
    households=[household for household in households if household is not None]
    if len(households)!=1:
     return web.json_response({'error':'burtracker_not_configured'},status=HTTPStatus.SERVICE_UNAVAILABLE)
    retailer=households[0].retailer
    if action == 'kronan_search':
     result=await retailer.search_products(args.get('query'),store=args.get('store'),page=args.get('page',1),page_size=args.get('page_size',15))
    elif action == 'kronan_stores':result=await retailer.scan_n_go_stores()
    elif action == 'kronan_recipe_search':result=await retailer.search_recipes(args.get('query',''),args.get('page',1))
    elif action == 'kronan_recipe':result=await retailer.recipe_detail(args.get('slug'))
    elif action == 'quote_kronan_recipe':
     preferences=meal_store.get_settings().get('household_dietary_preferences',{})
     async with asyncio.timeout(60):
      result=await retailer.quote_recipe(args.get('slug'),args.get('portions'),preferences)
     result['day']=args.get('day')
     if result['complete']:result=meal_store.create_quote(result)
    elif action == 'quote_generated_meal':
     preferences=meal_store.get_settings().get('household_dietary_preferences',{})
     async with asyncio.timeout(60):
      result=await retailer.quote_generated_meal(args.get('title'),args.get('portions'),args.get('items'),args.get('instructions',''),args.get('source_url'),preferences)
     result['day']=args.get('day')
     result['budget_assessment']=meal_store.budget_assessment(args.get('day'),result['total_package_cost_isk']) if result.get('complete') else None
     if result['complete']:result=meal_store.create_quote(result)
    else:
     result=meal_store.commit_quote(args.get('quote_id'),args.get('replace_existing',False))
     hass.bus.async_fire('burtracker_meal_updated',{'day':result.get('day')})
    return web.json_response({'ok':True,'result':result})
   result=api_call(action,**args)
   return web.json_response({'ok':True,'result':result})
  except (ValueError,KeyError,TypeError) as err:
   return web.json_response({'error':str(err)},status=HTTPStatus.BAD_REQUEST)
  except LookupError as err:
   return web.json_response({'error':str(err)},status=HTTPStatus.NOT_FOUND)
  except LookupFailure as err:
   status=HTTPStatus.TOO_MANY_REQUESTS if err.status=='rate_limited' else HTTPStatus.BAD_GATEWAY
   return web.json_response({'error':err.status},status=status)
  except TimeoutError:
   return web.json_response({'error':'kronan_timeout'},status=HTTPStatus.GATEWAY_TIMEOUT)
  except Exception:
   return web.json_response({'error':'internal_error'},status=HTTPStatus.INTERNAL_SERVER_ERROR)

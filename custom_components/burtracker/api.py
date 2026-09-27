"""Home Assistant REST bridge for BurTracker meal records."""
from http import HTTPStatus
import json
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from .meals import api_call

class MealPlannerView(HomeAssistantView):
 url = "/api/burtracker/meals/{action}"
 name = "api:burtracker:meals"
 requires_auth = True

 async def get(self, request, action):
  try:
   args={k:request.query[k] for k in request.query}
   return web.json_response(api_call(action,**args))
  except (ValueError,KeyError) as err:
   return web.json_response({'error':str(err)},status=HTTPStatus.BAD_REQUEST)
  except LookupError as err:
   return web.json_response({'error':str(err)},status=HTTPStatus.NOT_FOUND)
  except Exception:
   return web.json_response({'error':'internal_error'},status=HTTPStatus.INTERNAL_SERVER_ERROR)

 async def post(self, request, action):
  try:
   args=await request.json()
   if not isinstance(args,dict):raise ValueError('JSON object required')
   result=api_call(action,**args)
   return web.json_response({'ok':True,'result':result})
  except (ValueError,KeyError,TypeError) as err:
   return web.json_response({'error':str(err)},status=HTTPStatus.BAD_REQUEST)
  except LookupError as err:
   return web.json_response({'error':str(err)},status=HTTPStatus.NOT_FOUND)
  except Exception:
   return web.json_response({'error':'internal_error'},status=HTTPStatus.INTERNAL_SERVER_ERROR)

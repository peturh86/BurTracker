"""BurTracker's tiny durable meal-planning store and Home Assistant API."""
from datetime import date as Date, datetime, timedelta, timezone
import logging
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

DB = Path(__file__).resolve().parents[2] / ".storage" / "burtracker_meals.db"
_LOGGER = logging.getLogger(__name__)
SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS recipes (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, source_url TEXT,
 servings REAL NOT NULL CHECK(servings>0), ingredients TEXT NOT NULL,
 instructions TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS meals (
 id INTEGER PRIMARY KEY, day TEXT NOT NULL UNIQUE, recipe_id INTEGER REFERENCES recipes(id),
 title TEXT NOT NULL, portions REAL NOT NULL CHECK(portions>0),
 status TEXT NOT NULL DEFAULT 'planned' CHECK(status IN ('planned','cooked','not_home','ate_out','cancelled')),
 cost_isk INTEGER CHECK(cost_isk IS NULL OR cost_isk>=0), notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS feedback (
 id INTEGER PRIMARY KEY, meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
 metric TEXT NOT NULL CHECK(metric IN ('enjoyment','taste','difficulty','portions','approval','cost','other')),
 score INTEGER CHECK(score IS NULL OR score BETWEEN 1 AND 5), comment TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS pantry_observations (
 id INTEGER PRIMARY KEY, tracker TEXT NOT NULL DEFAULT '', request_id TEXT NOT NULL DEFAULT '',
 barcode TEXT NOT NULL, product_name TEXT NOT NULL DEFAULT '',
 seen_at TEXT NOT NULL, confirmed_packages INTEGER CHECK(confirmed_packages IS NULL OR confirmed_packages>=0),
 source TEXT NOT NULL DEFAULT 'burtracker'
);
CREATE UNIQUE INDEX IF NOT EXISTS pantry_event_once ON pantry_observations(tracker,request_id) WHERE request_id!='';
CREATE TABLE IF NOT EXISTS purchases (
 id INTEGER PRIMARY KEY, purchased_at TEXT NOT NULL, total_isk INTEGER NOT NULL CHECK(total_isk>=0), note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS budget_targets (
 period TEXT PRIMARY KEY CHECK(period IN ('week','month')), target_isk INTEGER NOT NULL CHECK(target_isk>=0), effective_from TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS special_event_allocations (
 id INTEGER PRIMARY KEY, event_date TEXT NOT NULL, label TEXT NOT NULL, planned_cost_isk INTEGER NOT NULL CHECK(planned_cost_isk>=0)
);
CREATE TABLE IF NOT EXISTS meal_quotes (
 id TEXT PRIMARY KEY, planned_day TEXT NOT NULL, payload_json TEXT NOT NULL,
 created_at TEXT NOT NULL, saved_meal_id INTEGER REFERENCES meals(id)
);
CREATE TABLE IF NOT EXISTS meal_shopping_items (
 id INTEGER PRIMARY KEY, meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
 sku TEXT NOT NULL, product_name TEXT NOT NULL, packages INTEGER NOT NULL CHECK(packages>0),
 unit_price_isk INTEGER NOT NULL CHECK(unit_price_isk>=0),
 line_total_isk INTEGER NOT NULL CHECK(line_total_isk>=0), price_info TEXT NOT NULL DEFAULT '',
 observed_at TEXT NOT NULL, source_url TEXT NOT NULL, charged_by_weight INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS meal_shopping_by_meal ON meal_shopping_items(meal_id);
CREATE INDEX IF NOT EXISTS pantry_by_barcode_seen ON pantry_observations(barcode,seen_at DESC);
"""

def connect():
 DB.parent.mkdir(parents=True,exist_ok=True)
 c=sqlite3.connect(DB,timeout=5)
 c.row_factory=sqlite3.Row
 c.execute('PRAGMA foreign_keys=ON')
 return c

def init():
 with connect() as c:
  c.executescript(SCHEMA)
  _migrate_feedback_metrics(c)
  c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('household_baseline',?)",(json.dumps({'members':[{'role':'adult','count':2},{'role':'child','age':10,'count':1},{'role':'child','age':7,'count':1}],'child_portion_factor':0.75,'factor_is_provisional':True}),))
  c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('household_dietary_preferences',?)",(json.dumps({
   'lactose_free': True,
   'pregnancy_food_safety': True,
   'blood_sugar_consideration': True,
   'guidance': 'Household preferences, not medical advice. Follow the pregnant person’s clinician for individualized food-safety and blood-sugar guidance.'
  },ensure_ascii=False),))

def _migrate_feedback_metrics(c):
 row=c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='feedback'").fetchone()
 if not row or 'enjoyment' in (row['sql'] or '').lower():return
 c.execute('BEGIN IMMEDIATE')
 c.execute('ALTER TABLE feedback RENAME TO feedback_legacy')
 c.execute('''CREATE TABLE feedback_new (
  id INTEGER PRIMARY KEY, meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
  metric TEXT NOT NULL CHECK(metric IN ('enjoyment','taste','difficulty','portions','approval','cost','other')),
  score INTEGER CHECK(score IS NULL OR score BETWEEN 1 AND 5), comment TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
 )''')
 c.execute('INSERT INTO feedback_new(id,meal_id,metric,score,comment,created_at) SELECT id,meal_id,metric,score,comment,created_at FROM feedback_legacy')
 c.execute('DROP TABLE feedback_legacy')
 c.execute('ALTER TABLE feedback_new RENAME TO feedback')

def get_settings():
 with connect() as c:return {r['key']:json.loads(r['value']) for r in c.execute('SELECT key,value FROM settings')}

def set_setting(key,value):
 if key not in {'household_baseline','budget_calibration','household_dietary_preferences'}:raise ValueError('unsupported setting')
 with connect() as c:c.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value,ensure_ascii=False)))

def recipes():
 with connect() as c:return [dict(r) for r in c.execute('SELECT * FROM recipes ORDER BY name')]

def meals(start=None,end=None):
 start,end=start or Date.today().isoformat(),end or (Date.today()+timedelta(days=6)).isoformat()
 with connect() as c:return [dict(r) for r in c.execute('SELECT m.*,r.name AS recipe_name,r.source_url,r.ingredients,r.instructions FROM meals m LEFT JOIN recipes r ON r.id=m.recipe_id WHERE day BETWEEN ? AND ? ORDER BY day',(start,end))]

def upsert_recipe(name,servings,ingredients,instructions='',source_url=None,notes=''):
 if not isinstance(name,str) or not name.strip() or float(servings)<=0:raise ValueError('valid recipe name and servings required')
 if not isinstance(ingredients,str):ingredients=json.dumps(ingredients,ensure_ascii=False)
 with connect() as c:
  c.execute('INSERT INTO recipes(name,source_url,servings,ingredients,instructions,notes) VALUES(?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET source_url=excluded.source_url,servings=excluded.servings,ingredients=excluded.ingredients,instructions=excluded.instructions,notes=excluded.notes',(name.strip(),source_url,float(servings),ingredients,instructions,notes))

def find_recipe(query):
 with connect() as c:
  return [dict(r) for r in c.execute('SELECT id,name,source_url,servings,ingredients,instructions FROM recipes WHERE name LIKE ? ORDER BY name LIMIT 10',(f'%{query}%',))]

def get_recipe(recipe_id):
 with connect() as c:
  row=c.execute('SELECT * FROM recipes WHERE id=?',(recipe_id,)).fetchone()
  return dict(row) if row else None

def upsert_meal(day,title,portions,recipe_id=None,cost_isk=None,notes=''):
 Date.fromisoformat(day)
 if not title.strip() or float(portions)<=0 or (cost_isk is not None and int(cost_isk)<0):raise ValueError('invalid meal')
 with connect() as c:c.execute('INSERT INTO meals(day,recipe_id,title,portions,cost_isk,notes) VALUES(?,?,?,?,?,?) ON CONFLICT(day) DO UPDATE SET recipe_id=excluded.recipe_id,title=excluded.title,portions=excluded.portions,cost_isk=excluded.cost_isk,notes=excluded.notes',(day,recipe_id,title.strip(),float(portions),cost_isk,notes))

def create_quote(payload):
 if not isinstance(payload,dict) or payload.get('complete') is not True:raise ValueError('only complete, priced Krónan quotes can be saved')
 day=payload.get('day')
 Date.fromisoformat(day)
 title=payload.get('title')
 portions=payload.get('portions')
 lines=payload.get('product_lines')
 if not isinstance(title,str) or not title.strip() or not isinstance(portions,(int,float)) or isinstance(portions,bool) or portions<=0:raise ValueError('valid title and portions required')
 if not isinstance(lines,list) or not lines or len(lines)>100:raise ValueError('quote must contain priced Krónan product lines')
 total=0
 for line in lines:
  product=line.get('product') if isinstance(line,dict) else None
  packages=line.get('packages') if isinstance(line,dict) else None
  if not isinstance(product,dict) or type(packages) is not int or packages<1:raise ValueError('each line needs a verified product and positive whole-package quantity')
  price=product.get('price_isk')
  if not isinstance(product.get('sku'),str) or not isinstance(product.get('name'),str) or type(price) is not int or price<0 or product.get('temporary_shortage') is True:
   raise ValueError('all products must have a current price and no reported temporary shortage')
  line_total=price*packages
  if line.get('line_total_isk')!=line_total:raise ValueError('line total does not match verified unit price and package count')
  total+=line_total
 if payload.get('total_package_cost_isk')!=total:raise ValueError('quote total does not match its line items')
 if payload.get('complete') is not True:raise ValueError('quote must be explicitly complete')
 if not isinstance(payload.get('mapping_warning'),str) or not payload['mapping_warning'].strip():raise ValueError('quote must include ingredient-mapping provenance')
 quote_id=str(uuid4())
 stored=dict(payload,quote_id=quote_id)
 created=datetime.now(timezone.utc).isoformat()
 with connect() as c:c.execute('INSERT INTO meal_quotes(id,planned_day,payload_json,created_at) VALUES(?,?,?,?)',(quote_id,day,json.dumps(stored,ensure_ascii=False),created))
 return dict(stored,created_at=created)

def read_quote(quote_id):
 with connect() as c:
  row=c.execute('SELECT payload_json,created_at,saved_meal_id FROM meal_quotes WHERE id=?',(quote_id,)).fetchone()
  if not row:raise LookupError('quote not found')
  return dict(json.loads(row['payload_json']),created_at=row['created_at'],saved_meal_id=row['saved_meal_id'])

def commit_quote(quote_id,replace_existing=False):
 if not isinstance(quote_id,str) or not quote_id:raise ValueError('quote_id required')
 if type(replace_existing) is not bool:raise ValueError('replace_existing must be boolean')
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  quote_row=c.execute('SELECT * FROM meal_quotes WHERE id=?',(quote_id,)).fetchone()
  if not quote_row:raise LookupError('quote not found')
  if quote_row['saved_meal_id'] is not None:
   row=c.execute('SELECT * FROM meals WHERE id=?',(quote_row['saved_meal_id'],)).fetchone()
   return dict(row) if row else {'id':quote_row['saved_meal_id'],'day':quote_row['planned_day'],'already_saved':True}
  created=datetime.fromisoformat(quote_row['created_at'])
  if created.tzinfo is None:created=created.replace(tzinfo=timezone.utc)
  if datetime.now(timezone.utc)-created>timedelta(hours=2):raise ValueError('quote expired; refresh Krónan prices before saving')
  quote=json.loads(quote_row['payload_json']); day=quote_row['planned_day']
  old=c.execute('SELECT id,recipe_id FROM meals WHERE day=?',(day,)).fetchone()
  if old and not replace_existing:raise ValueError('meal already planned for this date; explicit replace_existing is required')
  title=quote['title'].strip(); recipe=c.execute('SELECT id FROM recipes WHERE name=?',(title,)).fetchone()
  if recipe:
   rid=recipe['id']
   references=c.execute('SELECT COUNT(*) FROM meals WHERE recipe_id=? AND day<>?',(rid,day)).fetchone()[0]
   if references:
    base=f'{title} [{day}]'; unique=base; n=2
    while c.execute('SELECT 1 FROM recipes WHERE name=?',(unique,)).fetchone():unique=f'{base} #{n}';n+=1
    title_for_db=unique
    recipe=None
   elif not old or old['recipe_id']!=rid:
    title_for_db=None
   else:title_for_db=None
  else:title_for_db=None
  if recipe is None:
   if title_for_db is None:title_for_db=title
   cursor=c.execute('INSERT INTO recipes(name,source_url,servings,ingredients,instructions,notes) VALUES(?,?,?,?,?,?)',(
    title_for_db,quote.get('source_url'),float(quote.get('source_servings') or quote['portions']),
    quote.get('ingredients_text') or '',quote.get('instructions') or '',quote.get('price_note') or 'Krónan-priced meal'))
   recipe_id=cursor.lastrowid
  else:
   recipe_id=recipe['id']
   c.execute('UPDATE recipes SET source_url=?,servings=?,ingredients=?,instructions=?,notes=? WHERE id=?',(
    quote.get('source_url'),float(quote.get('source_servings') or quote['portions']),
    quote.get('ingredients_text') or '',quote.get('instructions') or '',quote.get('price_note') or 'Krónan-priced meal',recipe_id))
  notes=f"Krónan catalog quote {quote_id}; prices observed {quote.get('price_observed_at','')}"
  if old:
   meal_id=old['id']
   c.execute('DELETE FROM meal_shopping_items WHERE meal_id=?',(meal_id,))
   c.execute('UPDATE meals SET recipe_id=?,title=?,portions=?,status=\'planned\',cost_isk=?,notes=? WHERE id=?',(
    recipe_id,quote['title'],float(quote['portions']),int(quote['total_package_cost_isk']),notes,meal_id))
  else:
   cursor=c.execute('INSERT INTO meals(day,recipe_id,title,portions,status,cost_isk,notes) VALUES(?,?,?,?,?,?,?)',(
    day,recipe_id,quote['title'],float(quote['portions']),'planned',int(quote['total_package_cost_isk']),notes))
   meal_id=cursor.lastrowid
  for line in quote['product_lines']:
   product=line['product']
   c.execute('INSERT INTO meal_shopping_items(meal_id,sku,product_name,packages,unit_price_isk,line_total_isk,price_info,observed_at,source_url,charged_by_weight) VALUES(?,?,?,?,?,?,?,?,?,?)',(
    meal_id,product['sku'],product['name'],line['packages'],product['price_isk'],line['line_total_isk'],
    product.get('price_info') or '',product['observed_at'],product.get('source_url') or quote.get('source_url') or '',
    int(bool(product.get('charged_by_weight')))))
  c.execute('UPDATE meal_quotes SET saved_meal_id=? WHERE id=?',(meal_id,quote_id))
  row=c.execute('SELECT * FROM meals WHERE id=?',(meal_id,)).fetchone()
  return dict(row)

def meal_shopping_items(day):
 with connect() as c:
  return [dict(r) for r in c.execute('SELECT i.* FROM meal_shopping_items i JOIN meals m ON m.id=i.meal_id WHERE m.day=? ORDER BY i.product_name',(day,))]

def delete_meal(day):
 with connect() as c:return c.execute('DELETE FROM meals WHERE day=?',(day,)).rowcount

def set_status(day,status):
 if status not in {'planned','cooked','not_home','ate_out','cancelled'}:raise ValueError('invalid status')
 with connect() as c:
  if c.execute('UPDATE meals SET status=? WHERE day=?',(status,day)).rowcount!=1:raise LookupError('no planned meal that day')

def add_feedback(day,metric,score=None,comment=''):
 if metric not in {'enjoyment','taste','difficulty','portions','approval','cost','other'} or (score is not None and not 1<=int(score)<=5):raise ValueError('invalid feedback')
 with connect() as c:
  row=c.execute('SELECT id FROM meals WHERE day=?',(day,)).fetchone()
  if not row:raise LookupError('no meal for that date')
  c.execute('INSERT INTO feedback(meal_id,metric,score,comment) VALUES(?,?,?,?)',(row['id'],metric,score,comment[:2000]))

def observe_pantry(barcode,product_name='',seen_at=None,confirmed_packages=None,tracker='',request_id=''):
 if not isinstance(barcode,str) or not barcode.strip() or len(barcode)>128:raise ValueError('invalid barcode')
 if request_id and not tracker:raise ValueError('tracker required with request id')
 with connect() as c:
  c.execute('INSERT OR IGNORE INTO pantry_observations(tracker,request_id,barcode,product_name,seen_at,confirmed_packages) VALUES(?,?,?,?,?,?)',(tracker,request_id,barcode.strip(),product_name[:200],seen_at or Date.today().isoformat(),confirmed_packages))

def resolve_pantry(tracker,request_id,product_name):
 with connect() as c:
  c.execute('UPDATE pantry_observations SET product_name=? WHERE tracker=? AND request_id=?',(product_name[:200],tracker,request_id))

def recent_pantry(limit=100):
 with connect() as c:
  return [dict(r) for r in c.execute('''SELECT barcode,
   (SELECT product_name FROM pantry_observations p2 WHERE p2.barcode=p.barcode ORDER BY seen_at DESC,id DESC LIMIT 1) product_name,
   MAX(seen_at) seen_at,
   (SELECT confirmed_packages FROM pantry_observations p3 WHERE p3.barcode=p.barcode ORDER BY seen_at DESC,id DESC LIMIT 1) confirmed_packages,
   COUNT(*) scans,
   CAST(julianday('now')-julianday(MAX(seen_at)) AS INTEGER) days_since_seen,
   CASE WHEN julianday('now')-julianday(MAX(seen_at))<=7 THEN 'recent' WHEN julianday('now')-julianday(MAX(seen_at))<=30 THEN 'aging' ELSE 'stale' END confidence
   FROM pantry_observations p GROUP BY barcode ORDER BY seen_at DESC LIMIT ?''',(limit,))]

def recent_feedback(limit=50):
 with connect() as c:return [dict(r) for r in c.execute('SELECT f.*,m.day,m.title FROM feedback f JOIN meals m ON m.id=f.meal_id ORDER BY f.id DESC LIMIT ?',(limit,))]

def add_purchase(total_isk, purchased_at=None, note=''):
 if int(total_isk)<0:raise ValueError('purchase must be nonnegative')
 with connect() as c:c.execute('INSERT INTO purchases(purchased_at,total_isk,note) VALUES(?,?,?)',(purchased_at or Date.today().isoformat(),int(total_isk),note[:500]))

def budget_assessment(day, basket_cost_isk):
 """Compare a proposed whole-package basket with remaining meal-budget headroom.

 Budget plans use historical observed grocery purchases as the stable baseline;
 planned meals are not deducted from actual spend. No target means no verdict.
 """
 Date.fromisoformat(day)
 if type(basket_cost_isk) is not int or basket_cost_isk < 0:
  raise ValueError('basket_cost_isk must be a nonnegative integer')
 moment=Date.fromisoformat(day)
 with connect() as c:
  targets=[dict(r) for r in c.execute('SELECT * FROM budget_targets ORDER BY period')]
  result=[]
  for target in targets:
   period=target['period']
   if period=='week':
    start=(moment-timedelta(days=moment.weekday())).isoformat()
    end=(moment+timedelta(days=6-moment.weekday())).isoformat()
   else:
    start=moment.replace(day=1).isoformat()
    next_month=(moment.replace(day=28)+timedelta(days=4)).replace(day=1)
    end=(next_month-timedelta(days=1)).isoformat()
   if target['effective_from']>moment.isoformat():
    result.append(dict(period=period,target_isk=target['target_isk'],actual_spend_isk=0,
                       planned_meals_isk=0,remaining_isk=target['target_isk'],
                       proposed_basket_isk=basket_cost_isk,
                       within_target=basket_cost_isk<=target['target_isk'],status='future_target'))
    continue
   actual=c.execute('SELECT COALESCE(SUM(total_isk),0) FROM purchases WHERE purchased_at BETWEEN ? AND ?',
                     (max(start,target['effective_from']),end)).fetchone()[0]
   planned=c.execute("SELECT COALESCE(SUM(cost_isk),0) FROM meals WHERE day BETWEEN ? AND ? AND status='planned'",
                     (max(start,target['effective_from']),end)).fetchone()[0]
   remaining=max(0,target['target_isk']-actual)
   result.append(dict(period=period,target_isk=target['target_isk'],actual_spend_isk=actual,
                      planned_meals_isk=planned,remaining_isk=remaining,
                      proposed_basket_isk=basket_cost_isk,
                      within_target=actual+basket_cost_isk<=target['target_isk'],
                      projected_including_planned_isk=actual+planned+basket_cost_isk,
                      status='within_target' if actual+basket_cost_isk<=target['target_isk'] else 'over_target'))
 return {'as_of_date':day,'currency':'ISK','assessments':result,
         'note':'Actual grocery purchases determine remaining budget; planned meals are shown separately to avoid counting planned meals as actual spend. Whole-pack proposed basket compared; pantry deductions are not assumed.'}

def add_budget(period,target_isk,effective_from=None):
 if period not in {'week','month'} or type(target_isk) is not int or target_isk<0:raise ValueError('invalid budget')
 Date.fromisoformat(effective_from or Date.today().isoformat())
 with connect() as c:c.execute('INSERT INTO budget_targets(period,target_isk,effective_from) VALUES(?,?,?) ON CONFLICT(period) DO UPDATE SET target_isk=excluded.target_isk,effective_from=excluded.effective_from',(period,target_isk,effective_from or Date.today().isoformat()))


def get_budget():
 with connect() as c:return [dict(r) for r in c.execute('SELECT * FROM budget_targets ORDER BY period')]

def add_special_event(day,label,cost_isk):
 Date.fromisoformat(day)
 if not label.strip() or int(cost_isk)<0:raise ValueError('invalid allocation')
 with connect() as c:c.execute('INSERT INTO special_event_allocations(event_date,label,planned_cost_isk) VALUES(?,?,?)',(day,label.strip(),int(cost_isk)))

def api_call(action, **args):
    """Allowlisted operations for authenticated internal/API consumers."""
    operations = {
        'recipes': lambda: recipes(),
        'settings': lambda: get_settings(),
        'set_setting': lambda: set_setting(args['key'], args['value']),
        'find_recipe': lambda: find_recipe(args['query']),
        'get_recipe': lambda: get_recipe(args['id']),
        'meals': lambda: meals(args.get('start'), args.get('end')),
        'shopping_items': lambda: meal_shopping_items(args['day']),
        'upsert_recipe': lambda: upsert_recipe(**args),
        'upsert_meal': lambda: upsert_meal(**args),
        'delete_meal': lambda: delete_meal(args['day']),
        'set_status': lambda: set_status(args['day'], args['status']),
        'feedback': lambda: add_feedback(**args),
        'pantry': lambda: recent_pantry(),
        'observe_pantry': lambda: observe_pantry(**args),
        'feedback_history': lambda: recent_feedback(),
            'budget': lambda: get_budget(),
        'budget_assessment': lambda: budget_assessment(args['day'],args['basket_cost_isk']),
        'add_budget': lambda: add_budget(**args),
        'add_purchase': lambda: add_purchase(**args),
        'special_event': lambda: add_special_event(**args),
    }
    if action not in operations:
        raise ValueError('unsupported meal action')
    return operations[action]()

def demo():
 import tempfile
 global DB
 old=DB
 with tempfile.TemporaryDirectory() as d:
  DB=Path(d)/'test.db';init();upsert_recipe('Test stew',4,'["beans"]','Simmer')
  upsert_meal('2026-09-28','Test stew',3.5,1);add_feedback('2026-09-28','portions',2,'too little')
  set_status('2026-09-28','not_home');observe_pantry('00123','Noodles','2026-09-27',tracker='scanner',request_id='a');observe_pantry('00123','Noodles','2026-09-28',tracker='scanner',request_id='b');observe_pantry('00123','Noodles','2026-09-29',tracker='scanner',request_id='b')
  assert meals('2026-09-28','2026-09-28')[0]['status']=='not_home'
  assert recent_pantry()[0]['scans']==2 and recent_pantry()[0]['confirmed_packages'] is None
  assert len(recipes())==1
 DB=old
 print('meal store self-check passed')

if __name__=='__main__':demo()

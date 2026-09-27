"""BurTracker's tiny durable meal-planning store and Home Assistant API."""
from datetime import date as Date, timedelta
import logging
import json
from pathlib import Path
import sqlite3

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
  c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('household_baseline',?)",(json.dumps({'members':[{'role':'adult','count':2},{'role':'child','age':10,'count':1},{'role':'child','age':7,'count':1}],'child_portion_factor':0.75,'factor_is_provisional':True}),))

def get_settings():
 with connect() as c:return {r['key']:json.loads(r['value']) for r in c.execute('SELECT key,value FROM settings')}

def set_setting(key,value):
 if key not in {'household_baseline','budget_calibration'}:raise ValueError('unsupported setting')
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

def add_budget(period,target_isk,effective_from=None):
 if period not in {'week','month'} or int(target_isk)<0:raise ValueError('invalid budget')
 with connect() as c:c.execute('INSERT INTO budget_targets(period,target_isk,effective_from) VALUES(?,?,?) ON CONFLICT(period) DO UPDATE SET target_isk=excluded.target_isk,effective_from=excluded.effective_from',(period,int(target_isk),effective_from or Date.today().isoformat()))

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
        'upsert_recipe': lambda: upsert_recipe(**args),
        'upsert_meal': lambda: upsert_meal(**args),
        'delete_meal': lambda: delete_meal(args['day']),
        'set_status': lambda: set_status(args['day'], args['status']),
        'feedback': lambda: add_feedback(**args),
        'pantry': lambda: recent_pantry(),
        'observe_pantry': lambda: observe_pantry(**args),
        'feedback_history': lambda: recent_feedback(),
        'budget': lambda: get_budget(),
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

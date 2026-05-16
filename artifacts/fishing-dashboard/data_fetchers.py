import requests
import re
from datetime import datetime
from cache_utils import ttl_cache

USGS_API = "https://waterservices.usgs.gov/nwis/iv/"
USGS_SITE_API = "https://waterservices.usgs.gov/nwis/site/"

OREGON_GAGE_IDS = {
    "Deschutes River": "14103000",
    "McKenzie River": "14162500",
    "Crooked River": "14087400",
    "North Santiam River": "14185000",
    "South Santiam River": "14187500",
    "Sandy River": "14137000",
    "North Umpqua River": "14316500",
    "South Umpqua River": "14306500",
    "Rogue River": "14361500",
    "Illinois River": "14377100",
    "Applegate River": "14371500",
    "Wilson River": "14301500",
    "Nestucca River": "14303500",
    "Siletz River": "14305500",
    "Alsea River": "14306030",
    "Chetco River": "14400000",
    "Coquille River": "14323000",
    "Willamette River": "14211720",
    "Molalla River": "14200300",
    "Clackamas River": "14211010",
    "Yamhill River": "14194150",
    "Long Tom River": "14172000",
    "Middle Fork Willamette": "14152000",
    "Hood River": "14120000",
    "Umatilla River": "14020000",
    "Grande Ronde River": "13351000",
    "Imnaha River": "13337500",
    "John Day River": "14048000",
    "Owyhee River": "13183000",
    "Malheur River": "13186000",
    "Fall River": "14053500",
    "Williamson River": "11502000",
    "Klamath River": "11510700",
}

SPRING_FED_RIVERS = {
    "Metolius River": {
        "cfs": 1650,
        "note": "Spring-fed — no active USGS gage on upper river. Flows stable year-round (~1,500–1,800 CFS).",
        "datetime": "estimated",
        "temp_f": 48.0,
        "temp_note": "Spring-fed and nearly constant ~48°F year-round.",
    }
}

DAM_ANNOTATIONS = {
    "McKenzie River": [
        {"dam": "Leaburg Dam", "above_keywords": ["vida", "ab leaburg", "above leaburg"], "below_keywords": ["bl leaburg", "below leaburg", "springfield", "coburg"]},
    ],
    "South Fork McKenzie River": [
        {"dam": "Cougar Dam", "above_keywords": ["ab cougar", "above cougar", "cougar reservoir", "rainbow or"], "below_keywords": ["bl cougar", "below cougar"]},
    ],
    "Crooked River": [
        {"dam": "Bowman Dam", "above_keywords": ["ab bowman", "above bowman", "prineville res"], "below_keywords": ["bl bowman", "below bowman", "cobble", "hwy 27"]},
    ],
    "North Santiam River": [
        {"dam": "Detroit Dam", "above_keywords": ["ab detroit", "above detroit", "breitenbush", "upper santiam"], "below_keywords": ["bl detroit", "below detroit", "mehama", "mill city", "stayton"]},
    ],
    "Middle Fork Willamette": [
        {"dam": "Dexter Dam", "above_keywords": ["ab dexter", "above dexter", "hills creek", "lookout point", "oakridge"], "below_keywords": ["bl dexter", "below dexter", "lowell", "springfield"]},
    ],
    "Owyhee River": [
        {"dam": "Owyhee Dam", "above_keywords": ["ab owyhee dam", "above owyhee dam"], "below_keywords": ["bl owyhee", "below owyhee", "rome", "adrian"]},
    ],
    "Deschutes River": [
        {"dam": "Pelton Dam", "above_keywords": ["ab pelton", "above pelton", "madras", "culver"], "below_keywords": ["bl pelton", "below pelton", "maupin", "warm springs", "sherars"]},
    ],
}


def _annotate_dam_position(gauge: dict, river_name: str) -> dict:
    annotations = DAM_ANNOTATIONS.get(river_name, [])
    text = (gauge.get("name", "") + " " + gauge.get("location", "")).lower()
    for dam_info in annotations:
        for kw in dam_info.get("above_keywords", []):
            if kw in text:
                gauge["dam_position"] = "above"
                gauge["dam_name"] = dam_info["dam"]
                gauge["hydrology_type"] = "natural"
                return gauge
        for kw in dam_info.get("below_keywords", []):
            if kw in text:
                gauge["dam_position"] = "below"
                gauge["dam_name"] = dam_info["dam"]
                gauge["hydrology_type"] = "controlled"
                return gauge
    # Auto-detect USGS "BL DAM" / "AB DAM" abbreviations in station names
    if " bl " in text and "dam" in text:
        gauge["dam_position"] = "below"
        gauge["dam_name"] = None
        gauge["hydrology_type"] = "controlled"
    elif " ab " in text and ("dam" in text or "reservoir" in text or "res " in text):
        gauge["dam_position"] = "above"
        gauge["dam_name"] = None
        gauge["hydrology_type"] = "natural"
    else:
        gauge["dam_position"] = None
        gauge["dam_name"] = None
        gauge["hydrology_type"] = None
    return gauge


RIVER_INFO = {
    "Deschutes River": {"species": ["Rainbow Trout", "Brown Trout", "Summer Steelhead", "Fall Chinook"], "gear": ["Dry Fly", "Nymph", "Tenkara (upper)", "Steelhead gear (lower)"], "tenkara": True, "region": "Central Oregon", "season_note": "Year-round. Tenkara ideal above Bend May–Oct. Steelhead July–Oct (lower).", "access": "Bend, Maupin, Warm Springs, Hwy 97 corridors", "regulations": "Artificial lures only most sections. Check regs above/below Pelton Dam.", "drive_from_bend": 0},
    "McKenzie River": {"species": ["Rainbow Trout", "Spring Chinook", "Summer Steelhead", "Cutthroat"], "gear": ["Dry Fly", "Nymph", "Drift Boat", "Tenkara (forks)"], "tenkara": True, "region": "Willamette Valley", "season_note": "Best dry fly Apr–Oct. Chinook June–July. Steelhead July–Sept.", "access": "Eugene, Vida, Blue River, McKenzie Bridge (Hwy 126)", "regulations": "Wild trout C&R above Hayden Bridge. Chinook retention check regs.", "drive_from_bend": 75},
    "Metolius River": {"species": ["Rainbow Trout", "Brown Trout", "Bull Trout", "Brook Trout"], "gear": ["Dry Fly", "Nymph", "Tenkara"], "tenkara": True, "region": "Central Oregon", "season_note": "Year-round. Spring-fed, nearly constant temperature. Challenging technical fishing.", "access": "Camp Sherman, Black Butte, Hwy 20 corridor (Sisters)", "regulations": "Artificial flies and lures only. Bull trout C&R mandatory. No bait.", "drive_from_bend": 35},
    "Crooked River": {"species": ["Rainbow Trout", "Brown Trout"], "gear": ["Nymph", "Dry Fly", "Tenkara", "Midge"], "tenkara": True, "region": "Central Oregon", "season_note": "Year-round tailwater below Bowman Dam. Best midges Nov–Mar. Dries Apr–Oct.", "access": "Hwy 27 south of Prineville. Cobble Walk access.", "regulations": "Artificial lures only. Wild trout C&R below Bowman Dam (4 miles).", "drive_from_bend": 45},
    "Fall River": {"species": ["Rainbow Trout", "Brown Trout"], "gear": ["Dry Fly", "Nymph", "Tenkara"], "tenkara": True, "region": "Central Oregon", "season_note": "Year-round spring creek. Consistent flows, ultra-clear water. Expert level.", "access": "Sunriver area, La Pine (Deschutes National Forest road)", "regulations": "Fly and artificial only. Most water C&R. Check ODFW regs carefully.", "drive_from_bend": 30},
    "North Santiam River": {"species": ["Spring Chinook", "Winter Steelhead", "Rainbow Trout", "Cutthroat"], "gear": ["Nymph", "Spey", "Gear (steelhead)", "Tenkara (above Detroit)"], "tenkara": True, "region": "Willamette Valley", "season_note": "Chinook May–July. Steelhead Dec–Mar. Trout Apr–Oct.", "access": "Mehama, Gates, Mill City, Detroit (Hwy 22)", "regulations": "Wild steelhead C&R. Check hatchery fin-clip requirements.", "drive_from_bend": 90},
    "South Santiam River": {"species": ["Spring Chinook", "Winter Steelhead", "Rainbow Trout"], "gear": ["Nymph", "Gear (steelhead)", "Spinner"], "tenkara": False, "region": "Willamette Valley", "season_note": "Chinook May–Aug. Steelhead Dec–Mar.", "access": "Sweet Home, Foster Reservoir area (US-20)", "regulations": "Check hatchery vs wild regs carefully. Retention varies by location.", "drive_from_bend": 85},
    "Sandy River": {"species": ["Winter Steelhead", "Spring Chinook", "Fall Chinook", "Cutthroat"], "gear": ["Spey", "Float / Gear", "Fly (deadline area)"], "tenkara": True, "region": "Mt. Hood / Portland", "season_note": "Winter steelhead Dec–Mar. Spring Chinook May–July. Fall Chinook Sept–Nov.", "access": "Oxbow Regional Park, Revenue Bridge, Dodge Park (near Portland/Gresham)", "regulations": "Hatchery steelhead retention, wild C&R. Spring Chinook check regs.", "drive_from_bend": 120},
    "Clackamas River": {"species": ["Winter Steelhead", "Spring Chinook", "Coho", "Cutthroat"], "gear": ["Spey", "Float", "Nymph", "Spinner"], "tenkara": False, "region": "Mt. Hood / Portland", "season_note": "Steelhead Dec–Mar. Chinook Apr–July. Coho Oct–Nov.", "access": "Estacada, Barton Park, McIver Park (Hwy 224)", "regulations": "Hatchery retention rules apply. Wild steelhead C&R.", "drive_from_bend": 115},
    "Hood River": {"species": ["Summer Steelhead", "Spring Chinook", "Rainbow Trout"], "gear": ["Dry Fly", "Nymph", "Spey"], "tenkara": True, "region": "Columbia Gorge", "season_note": "Steelhead July–Sept. Chinook May–June. Trout Apr–Oct.", "access": "Hood River city, Odell, Parkdale (Hwy 35)", "regulations": "Check tribal and state regulations carefully — Columbia Gorge complexity.", "drive_from_bend": 65},
    "North Umpqua River": {"species": ["Summer Steelhead", "Spring Chinook", "Rainbow Trout"], "gear": ["Fly Only (upper)", "Spey", "Single-hand fly"], "tenkara": False, "region": "Southern Oregon", "season_note": "Summer steelhead June–Oct (best). Chinook May–June. Trout Apr–Oct.", "access": "Roseburg, Glide, Toketee Falls (Hwy 138). Fly-only section above Rock Creek.", "regulations": "FLY ONLY above Rock Creek confluence — no hardware. Wild steelhead C&R.", "drive_from_bend": 130},
    "South Umpqua River": {"species": ["Winter Steelhead", "Spring Chinook", "Smallmouth Bass"], "gear": ["Gear", "Spinner", "Plug"], "tenkara": False, "region": "Southern Oregon", "season_note": "Steelhead Dec–Mar. Chinook May–July.", "access": "Roseburg, Canyonville, Myrtle Creek (I-5 corridor)", "regulations": "Standard Oregon regs. Hatchery fish retention allowed.", "drive_from_bend": 140},
    "Rogue River": {"species": ["Spring Chinook", "Fall Chinook", "Coho", "Summer Steelhead", "Winter Steelhead", "Rainbow Trout"], "gear": ["Drift Boat", "Jet Boat", "Spey", "Gear", "Fly (upper)"], "tenkara": False, "region": "Southern Oregon", "season_note": "Chinook: May–July (spring), Aug–Oct (fall). Steelhead year-round. Trout Apr–Oct.", "access": "Grants Pass, Medford, Gold Beach (Hwy 62, I-5)", "regulations": "Complex — varies by section. Check wild/hatchery rules carefully.", "drive_from_bend": 185},
    "Illinois River": {"species": ["Winter Steelhead", "Spring Chinook", "Cutthroat"], "gear": ["Fly", "Gear (lower)", "Nymph"], "tenkara": False, "region": "Southern Oregon", "season_note": "Pristine wild river. Steelhead Jan–Apr. Chinook May–July.", "access": "Selma, Kerby, Cave Junction (US-199). Remote sections require hiking.", "regulations": "Wild steelhead C&R. Wilderness designation on much of river.", "drive_from_bend": 215},
    "Applegate River": {"species": ["Rainbow Trout", "Spring Chinook", "Smallmouth Bass"], "gear": ["Nymph", "Dry Fly", "Spinner"], "tenkara": True, "region": "Southern Oregon", "season_note": "Trout Apr–Oct. Chinook May–July. Small stream character.", "access": "Jacksonville, Applegate (Hwy 238)", "regulations": "Check wild trout regs. Chinook may be closed.", "drive_from_bend": 200},
    "Wilson River": {"species": ["Winter Steelhead", "Coho Salmon", "Cutthroat", "Rainbow Trout"], "gear": ["Float", "Spey", "Nymph", "Tenkara (forks)"], "tenkara": True, "region": "Oregon Coast", "season_note": "Steelhead Dec–Mar. Coho Oct–Dec. Trout Apr–Oct.", "access": "Tillamook, Tillamook State Forest (Hwy 6)", "regulations": "Wild steelhead C&R. Hatchery retention check current emergency orders.", "drive_from_bend": 155},
    "Nestucca River": {"species": ["Winter Steelhead", "Coho Salmon", "Spring Chinook", "Cutthroat"], "gear": ["Float", "Gear", "Fly"], "tenkara": False, "region": "Oregon Coast", "season_note": "Steelhead Nov–Mar. Coho Oct–Dec. Chinook May–July.", "access": "Cloverdale, Pacific City (Hwy 101, Hwy 130)", "regulations": "Wild steelhead C&R. Check ODFW emergency orders seasonally.", "drive_from_bend": 150},
    "Siletz River": {"species": ["Winter Steelhead", "Coho Salmon", "Chinook Salmon"], "gear": ["Float", "Gear", "Spey"], "tenkara": False, "region": "Oregon Coast", "season_note": "Steelhead Dec–Mar. Coho Oct–Dec.", "access": "Lincoln City, Siletz, Toledo (Hwy 229)", "regulations": "Wild steelhead C&R on most sections.", "drive_from_bend": 130},
    "Alsea River": {"species": ["Winter Steelhead", "Coho Salmon", "Cutthroat"], "gear": ["Float", "Gear"], "tenkara": False, "region": "Oregon Coast", "season_note": "Steelhead Nov–Mar. Coho Oct–Nov.", "access": "Alsea, Tidewater, Waldport (Hwy 34)", "regulations": "Wild steelhead C&R. Check sport season closures.", "drive_from_bend": 130},
    "Chetco River": {"species": ["Winter Steelhead", "Spring Chinook", "Coho"], "gear": ["Float", "Gear", "Fly"], "tenkara": False, "region": "Southern Oregon Coast", "season_note": "Steelhead Dec–Mar. Remote and wild — exceptional quality.", "access": "Brookings (Hwy 101, North Bank Road)", "regulations": "Wild steelhead C&R. One of Oregon's wildest river systems.", "drive_from_bend": 280},
    "Coquille River": {"species": ["Winter Steelhead", "Coho Salmon", "Cutthroat"], "gear": ["Gear", "Drift boat"], "tenkara": False, "region": "Southern Oregon Coast", "season_note": "Steelhead Nov–Mar. Coho Oct–Dec.", "access": "Myrtle Point, Coos Bay (Hwy 42)", "regulations": "Wild steelhead C&R. Coho check emergency regs.", "drive_from_bend": 195},
    "Willamette River": {"species": ["Spring Chinook", "Winter Steelhead", "Smallmouth Bass", "Walleye", "Shad"], "gear": ["Gear", "Trolling", "Spinner", "Fly (upper)"], "tenkara": False, "region": "Willamette Valley", "season_note": "Chinook Mar–June. Steelhead Dec–Mar. Spring shad great fun.", "access": "Portland, Salem, Albany, Corvallis (I-5 corridor)", "regulations": "Check wild chinook status. Bass season open year-round.", "drive_from_bend": 100},
    "Molalla River": {"species": ["Winter Steelhead", "Coho Salmon", "Cutthroat"], "gear": ["Float", "Gear", "Nymph"], "tenkara": False, "region": "Willamette Valley", "season_note": "Steelhead Dec–Mar. Coho Oct–Dec.", "access": "Molalla, Canby (Hwy 213)", "regulations": "Wild steelhead C&R.", "drive_from_bend": 115},
    "Yamhill River": {"species": ["Smallmouth Bass", "Largemouth Bass", "Crappie", "Catfish"], "gear": ["Spinner", "Plastic", "Float (catfish)"], "tenkara": False, "region": "Willamette Valley", "season_note": "Bass June–Sept best. Catfish June–Oct.", "access": "Lafayette, McMinnville (Hwy 99W)", "regulations": "Standard Oregon bass/warmwater regs.", "drive_from_bend": 110},
    "Long Tom River": {"species": ["Largemouth Bass", "Crappie", "Catfish", "Cutthroat"], "gear": ["Spinner", "Plastic", "Float"], "tenkara": False, "region": "Willamette Valley", "season_note": "Bass Apr–Oct. Crappie spring spawning (April–May excellent).", "access": "Monroe, Cheshire (Hwy 99W/36)", "regulations": "Standard Oregon regs.", "drive_from_bend": 110},
    "Middle Fork Willamette": {"species": ["Rainbow Trout", "Cutthroat", "Spring Chinook"], "gear": ["Nymph", "Dry Fly", "Tenkara (upper)"], "tenkara": True, "region": "Willamette Valley", "season_note": "Trout Apr–Oct. Chinook May–July above Dexter Dam.", "access": "Oakridge, Dexter, Lowell (Hwy 58)", "regulations": "Wild trout regs above Dexter. Standard below.", "drive_from_bend": 100},
    "Umatilla River": {"species": ["Summer Steelhead", "Spring Chinook", "Rainbow Trout"], "gear": ["Gear", "Spinner", "Nymph"], "tenkara": False, "region": "Eastern Oregon", "season_note": "Steelhead Aug–Oct. Chinook May–July.", "access": "Hermiston, Pendleton (I-84, Hwy 30)", "regulations": "Tribal regulations may apply. Check carefully.", "drive_from_bend": 160},
    "Grande Ronde River": {"species": ["Summer Steelhead", "Spring Chinook", "Rainbow Trout", "Smallmouth Bass"], "gear": ["Spey", "Gear", "Dry Fly (summer)"], "tenkara": False, "region": "Eastern Oregon", "season_note": "Summer steelhead June–Oct (excellent). Bass May–Sept.", "access": "La Grande, Troy, Elgin (Hwy 82/30, Hwy 3)", "regulations": "Wild steelhead C&R. Tribal boundary at Snake River confluence.", "drive_from_bend": 200},
    "Imnaha River": {"species": ["Summer Steelhead", "Spring Chinook", "Rainbow Trout"], "gear": ["Gear", "Spey", "Dry Fly"], "tenkara": True, "region": "Eastern Oregon", "season_note": "Steelhead Aug–Oct. Chinook June–July. Remote — plan ahead.", "access": "Imnaha, Joseph (Hwy 86, Forest Road 39)", "regulations": "Wild steelhead C&R. Remote canyon fishing.", "drive_from_bend": 230},
    "John Day River": {"species": ["Smallmouth Bass", "Redband Rainbow Trout", "Summer Steelhead"], "gear": ["Spinner", "Topwater (bass)", "Nymph", "Dry Fly"], "tenkara": True, "region": "Eastern Oregon", "season_note": "Bass June–Sept. Trout Apr–Oct. Premier float-trip river.", "access": "Spray, Fossil, Clarno, Cottonwood (Hwy 19/207)", "regulations": "Wild trout regs apply on most sections. Bass standard regs.", "drive_from_bend": 120},
    "Owyhee River": {"species": ["Rainbow Trout", "Smallmouth Bass", "Brown Trout"], "gear": ["Nymph", "Dry Fly", "Spinner"], "tenkara": True, "region": "Eastern Oregon", "season_note": "Best Apr–June below dam (tailwater). Warm and low by July.", "access": "Vale, Adrian, Owyhee Dam (Hwy 201)", "regulations": "Check dam release schedule. Tailwater trout below Owyhee Dam.", "drive_from_bend": 165},
    "Malheur River": {"species": ["Rainbow Trout", "Brown Trout", "Smallmouth Bass"], "gear": ["Nymph", "Dry Fly", "Spinner"], "tenkara": True, "region": "Eastern Oregon", "season_note": "Trout Apr–Oct. Good access near Juntura.", "access": "Juntura, Vale (Hwy 20)", "regulations": "Standard Oregon regs.", "drive_from_bend": 145},
    "Williamson River": {"species": ["Rainbow Trout", "Brown Trout", "Bull Trout"], "gear": ["Dry Fly", "Nymph", "Tenkara"], "tenkara": True, "region": "Southern Oregon (Klamath Basin)", "season_note": "Spring-fed quality river. Trout Apr–Oct. Large rainbows. Technical.", "access": "Chiloquin, Fort Klamath (Hwy 97/62)", "regulations": "Check tribal and state regs — Klamath Tribes involvement. C&R often required.", "drive_from_bend": 95},
    "Klamath River": {"species": ["Fall Chinook", "Coho Salmon", "Steelhead", "Rainbow Trout"], "gear": ["Gear", "Drift Boat", "Jet Boat", "Fly"], "tenkara": False, "region": "Southern Oregon", "season_note": "Post dam-removal restoration. Fall Chinook Sept–Nov. Check current status.", "access": "Klamath Falls, Keno area (Hwy 97/66)", "regulations": "Major dam removal project — fish runs recovering. Check ODFW for current status.", "drive_from_bend": 110},
}

TENKARA_RIVERS = {r for r, info in RIVER_INFO.items() if info.get("tenkara")}

RIVER_COORDS = {
    "Deschutes River": (44.6365, -121.1871),
    "McKenzie River": (44.1271, -122.4818),
    "Metolius River": (44.4774, -121.6310),
    "Crooked River": (44.3052, -120.8364),
    "North Santiam River": (44.7751, -122.6016),
    "South Santiam River": (44.4720, -122.7910),
    "Sandy River": (45.4001, -122.2609),
    "Clackamas River": (45.3798, -122.3738),
    "North Umpqua River": (43.3201, -122.9316),
    "South Umpqua River": (43.5310, -123.5740),
    "Rogue River": (42.4265, -123.3256),
    "Illinois River": (42.1500, -123.6700),
    "Applegate River": (42.0792, -123.1108),
    "Wilson River": (45.5271, -123.5501),
    "Nestucca River": (45.3273, -123.8700),
    "Siletz River": (44.8975, -123.9257),
    "Alsea River": (44.4071, -123.6068),
    "Chetco River": (42.0548, -124.1831),
    "Coquille River": (43.1188, -124.3521),
    "Willamette River": (45.5231, -122.6765),
    "Molalla River": (45.1320, -122.5740),
    "Yamhill River": (45.2010, -123.1150),
    "Long Tom River": (44.3170, -123.3280),
    "Middle Fork Willamette": (43.8590, -122.7250),
    "Hood River": (45.6840, -121.6920),
    "Umatilla River": (45.6640, -119.3680),
    "Grande Ronde River": (45.7410, -117.0440),
    "Imnaha River": (45.5027, -116.8330),
    "John Day River": (44.7440, -119.9650),
    "Owyhee River": (43.6630, -117.2480),
    "Malheur River": (43.7640, -118.0650),
    "Fall River": (43.8490, -121.5640),
    "Williamson River": (42.5510, -121.8880),
    "Klamath River": (42.1060, -121.7340),
}

TYPICAL_RANGES = {
    "Deschutes River": (200, 3000, 600, 1400),
    "McKenzie River": (300, 4000, 800, 2500),
    "Metolius River": (200, 2500, 400, 1200),
    "Crooked River": (30, 600, 80, 350),
    "Fall River": (20, 200, 40, 100),
    "North Santiam River": (400, 8000, 800, 3000),
    "South Santiam River": (300, 6000, 700, 2500),
    "Sandy River": (500, 10000, 800, 3500),
    "Clackamas River": (400, 10000, 700, 3000),
    "North Umpqua River": (500, 8000, 900, 3500),
    "South Umpqua River": (500, 8000, 800, 3000),
    "Rogue River": (800, 15000, 1200, 5000),
    "Illinois River": (200, 4000, 400, 1500),
    "Applegate River": (100, 3000, 200, 900),
    "Wilson River": (150, 5000, 400, 2000),
    "Nestucca River": (100, 3500, 250, 1500),
    "Siletz River": (150, 4000, 350, 1800),
    "Alsea River": (200, 5000, 400, 2000),
    "Chetco River": (200, 6000, 500, 2500),
    "Coquille River": (300, 6000, 600, 2500),
    "Willamette River": (3000, 80000, 6000, 25000),
    "Molalla River": (100, 5000, 250, 2000),
    "Yamhill River": (100, 3000, 200, 1200),
    "Long Tom River": (50, 1500, 100, 600),
    "Middle Fork Willamette": (300, 5000, 700, 2500),
    "Hood River": (200, 4000, 400, 1800),
    "Umatilla River": (200, 4000, 500, 2000),
    "Grande Ronde River": (500, 8000, 1000, 3500),
    "Imnaha River": (200, 4000, 400, 1800),
    "John Day River": (300, 6000, 600, 2500),
    "Owyhee River": (100, 3000, 200, 1000),
    "Malheur River": (100, 2500, 200, 900),
    "Williamson River": (200, 3000, 400, 1500),
    "Klamath River": (1000, 20000, 2000, 8000),
}

IDEAL_TEMP_RANGE = (50, 68)

RIVER_ALIAS_OVERRIDES = {
    "McKenzie River": ["mckenzie", "south fork mckenzie", "sf mckenzie", "so fk mckenzie"],
    "Middle Fork Willamette": ["middle fork willamette", "mf willamette"],
    "North Santiam River": ["north santiam", "n santiam", "nf santiam"],
    "South Santiam River": ["south santiam", "s santiam", "sf santiam"],
    "North Umpqua River": ["north umpqua", "n umpqua", "nf umpqua"],
    "South Umpqua River": ["south umpqua", "s umpqua", "sf umpqua"],
}

_RIVER_NAME_STOP_WORDS = {"river", "creek", "the"}
_AMBIGUOUS_SINGLE_WORD_ALIASES = {"fall", "long", "middle", "north", "south"}


def _normalize_match_text(text: str) -> str:
    cleaned = (text or "").lower().replace("(est)", " ")
    cleaned = re.sub(r"\bsouth\s+fork\b", "sf", cleaned)
    cleaned = re.sub(r"\bso\s*fk\b", "sf", cleaned)
    cleaned = re.sub(r"\bs\s*fk\b", "sf", cleaned)
    cleaned = re.sub(r"\bnorth\s+fork\b", "nf", cleaned)
    cleaned = re.sub(r"\bn\s*fk\b", "nf", cleaned)
    cleaned = re.sub(r"\bmiddle\s+fork\b", "mf", cleaned)
    cleaned = re.sub(r"\bm\s*fk\b", "mf", cleaned)
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _build_river_match_aliases() -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = {}
    for river_name in RIVER_COORDS.keys():
        base = _normalize_match_text(river_name)
        alias_set = {base} if base else set()
        trimmed = " ".join(w for w in base.split() if w not in _RIVER_NAME_STOP_WORDS)
        if trimmed:
            tokens = trimmed.split()
            if len(tokens) >= 2 or (len(tokens) == 1 and tokens[0] not in _AMBIGUOUS_SINGLE_WORD_ALIASES):
                alias_set.add(trimmed)
        for extra in RIVER_ALIAS_OVERRIDES.get(river_name, []):
            norm_extra = _normalize_match_text(extra)
            if norm_extra:
                alias_set.add(norm_extra)
        aliases[river_name] = alias_set
    return aliases


RIVER_MATCH_ALIASES = _build_river_match_aliases()


def _match_river_systems(name: str, location: str = "", drainage: str = "") -> list[str]:
    haystack = _normalize_match_text(" ".join(filter(None, [name, location, drainage])))
    if not haystack:
        return []
    matched = []
    for river_name, aliases in RIVER_MATCH_ALIASES.items():
        if any(alias and alias in haystack for alias in aliases):
            matched.append(river_name)
    return matched


def filter_gauges_for_river_system(gauges: list[dict], river_query: str) -> list[dict]:
    norm_query = _normalize_match_text(river_query)
    if not norm_query:
        return gauges

    target_rivers = []
    for river_name, aliases in RIVER_MATCH_ALIASES.items():
        if any(norm_query in alias or alias in norm_query for alias in aliases):
            target_rivers.append(river_name)

    filtered = []
    for gauge in gauges:
        matched_rivers = _match_river_systems(
            name=gauge.get("name", ""),
            location=gauge.get("location", ""),
            drainage=gauge.get("drainage", ""),
        )
        if any(r in matched_rivers for r in target_rivers):
            filtered.append(gauge)
            continue

        combined = _normalize_match_text(
            " ".join(
                filter(
                    None,
                    [gauge.get("name", ""), gauge.get("location", ""), gauge.get("drainage", "")],
                )
            )
        )
        if norm_query and norm_query in combined:
            filtered.append(gauge)
    return filtered


def _safe_float(value):
    try:
        if value in (None, "", "-999999"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _latest_numeric_value(values: list[dict]) -> tuple[float | None, str]:
    for point in reversed(values or []):
        numeric = _safe_float(point.get("value"))
        if numeric is not None:
            return numeric, point.get("dateTime", "")
    return None, ""


def _parse_rdb_rows(raw_text: str) -> tuple[list[str], list[list[str]]]:
    lines = [ln for ln in (raw_text or "").splitlines() if ln and not ln.startswith("#")]
    if len(lines) < 3:
        return [], []
    header = lines[0].split("\t")
    rows = [ln.split("\t") for ln in lines[2:]]
    return header, rows


@ttl_cache(ttl=86400)
def fetch_usgs_site_catalog() -> list[dict]:
    try:
        resp = requests.get(
            USGS_SITE_API,
            params={
                "format": "rdb",
                "stateCd": "or",
                "siteType": "ST",
                "siteStatus": "active",
                "hasDataTypeCd": "iv",
                "parameterCd": "00060",
            },
            timeout=25,
        )
        resp.raise_for_status()
        header, rows = _parse_rdb_rows(resp.text)
        if not header:
            return []

        idx_site = header.index("site_no") if "site_no" in header else None
        idx_name = header.index("station_nm") if "station_nm" in header else None
        idx_lat = header.index("dec_lat_va") if "dec_lat_va" in header else None
        idx_lon = header.index("dec_long_va") if "dec_long_va" in header else None
        idx_type = header.index("site_tp_cd") if "site_tp_cd" in header else None
        if idx_site is None or idx_name is None:
            return []

        catalog = []
        for cols in rows:
            if len(cols) <= idx_name:
                continue
            site_id = cols[idx_site].strip() if len(cols) > idx_site else ""
            station_name = cols[idx_name].strip() if len(cols) > idx_name else ""
            site_type = cols[idx_type].strip() if idx_type is not None and len(cols) > idx_type else ""
            if not site_id or not station_name:
                continue
            if site_type and not site_type.startswith("ST"):
                continue
            catalog.append(
                {
                    "site_id": site_id,
                    "station_name": station_name,
                    "lat": _safe_float(cols[idx_lat]) if idx_lat is not None and len(cols) > idx_lat else None,
                    "lon": _safe_float(cols[idx_lon]) if idx_lon is not None and len(cols) > idx_lon else None,
                }
            )
        catalog.sort(key=lambda x: x["site_id"])
        return catalog
    except Exception:
        return []


@ttl_cache(ttl=300)
def fetch_usgs_site_values(site_ids_csv: str) -> dict:
    site_ids = [s.strip() for s in (site_ids_csv or "").split(",") if s.strip()]
    if not site_ids:
        return {}

    values_by_site: dict[str, dict] = {}
    chunk_size = 80
    for start in range(0, len(site_ids), chunk_size):
        chunk = site_ids[start:start + chunk_size]
        try:
            resp = requests.get(
                USGS_API,
                params={
                    "format": "json",
                    "sites": ",".join(chunk),
                    "parameterCd": "00060,00010,00065,63680,00300,00400,00095",
                    "siteStatus": "active",
                },
                timeout=20,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            continue

        for ts in payload.get("value", {}).get("timeSeries", []):
            site_code = ts.get("sourceInfo", {}).get("siteCode", [{}])[0].get("value")
            if not site_code:
                continue
            param_code = ts.get("variable", {}).get("variableCode", [{}])[0].get("value")
            if not param_code:
                continue
            numeric, dt_str = _latest_numeric_value(ts.get("values", [{}])[0].get("value", []))
            if numeric is None:
                continue

            site_entry = values_by_site.setdefault(
                site_code,
                {
                    "site_id": site_code,
                    "station_name": ts.get("sourceInfo", {}).get("siteName", ""),
                    "datetime": dt_str,
                    "source": "usgs_live",
                },
            )
            if dt_str and not site_entry.get("datetime"):
                site_entry["datetime"] = dt_str

            if param_code == "00060":
                site_entry["cfs"] = numeric
            elif param_code == "00010":
                site_entry["temp_c"] = numeric
                site_entry["temp_f"] = round(numeric * 9 / 5 + 32, 1)
            elif param_code == "00065":
                site_entry["stage_ft"] = numeric
            elif param_code == "63680":
                site_entry["turbidity_fnu"] = numeric
                site_entry["clarity"] = get_turbidity_label(numeric)
            elif param_code == "00300":
                site_entry["dissolved_oxygen_mgl"] = numeric
                site_entry["do_condition"] = get_do_condition(numeric)
            elif param_code == "00400":
                site_entry["ph"] = numeric
                site_entry["ph_condition"] = get_ph_condition(numeric)
            elif param_code == "00095":
                site_entry["specific_conductance_uscm"] = numeric
    return values_by_site


@ttl_cache(ttl=300)
def fetch_usgs_flows():
    results = {}
    try:
        catalog = fetch_usgs_site_catalog()
        site_matches = {}
        for site in catalog:
            matched = _match_river_systems(name=site.get("station_name", ""))
            if matched:
                site_matches[site["site_id"]] = matched

        primary_ids = set(OREGON_GAGE_IDS.values())
        selected_site_ids = sorted(set(site_matches.keys()) | primary_ids)
        site_ids_csv = ",".join(selected_site_ids)
        site_values = fetch_usgs_site_values(site_ids_csv)
        catalog_by_id = {site["site_id"]: site for site in catalog}
        gauges_by_river: dict[str, list[dict]] = {river: [] for river in RIVER_COORDS.keys()}

        for site_id, site_data in site_values.items():
            site_meta = catalog_by_id.get(site_id, {})
            station_name = site_data.get("station_name") or site_meta.get("station_name", "")
            if not station_name:
                continue

            matched_rivers = site_matches.get(site_id) or _match_river_systems(name=station_name)
            if not matched_rivers:
                continue

            gauge = {
                "id": f"USGS-{site_id}",
                "source": "USGS",
                "site_id": site_id,
                "name": station_name,
                "location": station_name,
                "drainage": "",
                "status": "",
                "status_color": "#00ccff",
                "datetime": site_data.get("datetime", ""),
                "flow_cfs": site_data.get("cfs"),
                "height_ft": site_data.get("stage_ft"),
                "temp_f": site_data.get("temp_f"),
                "flow_trend": "stable",
                "temp_trend": "stable",
                "whitewater_class": "",
                "lat": site_meta.get("lat"),
                "lon": site_meta.get("lon"),
                "turbidity_fnu": site_data.get("turbidity_fnu"),
                "clarity": site_data.get("clarity"),
                "dissolved_oxygen_mgl": site_data.get("dissolved_oxygen_mgl"),
                "do_condition": site_data.get("do_condition"),
                "ph": site_data.get("ph"),
                "ph_condition": site_data.get("ph_condition"),
                "specific_conductance_uscm": site_data.get("specific_conductance_uscm"),
            }
            for river_name in matched_rivers:
                gauges_by_river[river_name].append(_annotate_dam_position(gauge.copy(), river_name))
    except Exception as e:
        results["error"] = str(e)
        gauges_by_river = {river: [] for river in RIVER_COORDS.keys()}

    try:
        from wkcc_fetcher import fetch_wkcc_levels
        wkcc_gauges = fetch_wkcc_levels().get("gauges", [])
    except Exception:
        wkcc_gauges = []

    for wk in wkcc_gauges:
        matched_rivers = _match_river_systems(
            name=wk.get("name", ""),
            location=wk.get("location", ""),
            drainage=wk.get("drainage", ""),
        )
        if not matched_rivers:
            continue
        wkcc_id = f"WKCC-{_normalize_match_text(wk.get('name', ''))}-{_normalize_match_text(wk.get('location', ''))}"
        gauge = {
            "id": wkcc_id,
            "source": "WKCC",
            "site_id": None,
            "name": wk.get("name", ""),
            "location": wk.get("location", ""),
            "drainage": wk.get("drainage", ""),
            "status": wk.get("status", ""),
            "status_color": wk.get("status_color", "#888888"),
            "datetime": wk.get("datetime", ""),
            "flow_cfs": wk.get("flow_cfs"),
            "height_ft": wk.get("height_ft"),
            "temp_f": wk.get("temp_f"),
            "flow_trend": wk.get("flow_trend", "stable"),
            "temp_trend": wk.get("temp_trend", "stable"),
            "whitewater_class": wk.get("whitewater_class", ""),
            "lat": None,
            "lon": None,
        }
        for river_name in matched_rivers:
            gauges_by_river.setdefault(river_name, []).append(_annotate_dam_position(gauge.copy(), river_name))

    for river_name, gauge_list in gauges_by_river.items():
        unique = {}
        for gauge in gauge_list:
            gauge_id = gauge.get("id")
            if gauge_id:
                unique[gauge_id] = gauge
        deduped = list(unique.values())
        deduped.sort(
            key=lambda g: (
                0 if g.get("source") == "USGS" else 1,
                0 if g.get("flow_cfs") is not None else 1,
                g.get("name", ""),
            )
        )
        primary_site_id = OREGON_GAGE_IDS.get(river_name)
        primary = next((g for g in deduped if g.get("site_id") == primary_site_id), None) if primary_site_id else None
        if primary is None and deduped:
            primary = deduped[0]

        if primary:
            results[river_name] = {
                "cfs": primary.get("flow_cfs"),
                "temp_f": primary.get("temp_f"),
                "temp_c": round((primary["temp_f"] - 32) * 5 / 9, 1) if primary.get("temp_f") is not None else None,
                "stage_ft": primary.get("height_ft"),
                "datetime": primary.get("datetime"),
                "site_id": primary.get("site_id"),
                "source": "usgs_live" if primary.get("source") == "USGS" else "wkcc_live",
                "clarity": primary.get("clarity"),
                "turbidity_fnu": primary.get("turbidity_fnu"),
                "dissolved_oxygen_mgl": primary.get("dissolved_oxygen_mgl"),
                "do_condition": primary.get("do_condition"),
                "ph": primary.get("ph"),
                "ph_condition": primary.get("ph_condition"),
                "specific_conductance_uscm": primary.get("specific_conductance_uscm"),
                "gauges": deduped,
                "primary_gauge": primary,
            }
        elif river_name not in results:
            results[river_name] = {"gauges": [], "primary_gauge": None}

    for river, meta in SPRING_FED_RIVERS.items():
        results[river] = {
            "cfs": meta["cfs"],
            "datetime": meta["datetime"],
            "site_id": None,
            "source": "spring_fed_estimate",
            "note": meta["note"],
            "temp_f": meta.get("temp_f"),
            "temp_c": round((meta["temp_f"] - 32) * 5 / 9, 1) if meta.get("temp_f") else None,
            "gauges": [],
            "primary_gauge": None,
        }
    return results


@ttl_cache(ttl=3600)
def fetch_odfw_stocking():
    try:
        requests.get("https://myodfw.com/articles/where-fish-odfw-stocking-schedule", timeout=8, headers={"User-Agent": "OregonFishingDashboard/4.0"})
        return _parse_stocking_fallback()
    except Exception:
        return _parse_stocking_fallback()


def _parse_stocking_fallback():
    today = datetime.now()
    month = today.month
    base = {"date": today.strftime("%Y-%m-%d"), "source": "ODFW seasonal pattern"}
    if month in [3, 4, 5]:
        return [
            {**base, "river": "Deschutes River", "location": "Bend City Reach", "species": "Rainbow Trout", "size": "10–12 inch", "note": "April–May peak."},
            {**base, "river": "Willamette River", "location": "Corvallis / Albany", "species": "Rainbow Trout", "size": "10–12 inch", "note": "Multiple urban access points."},
            {**base, "river": "Sandy River", "location": "Oxbow Park / Revenue Bridge", "species": "Winter Steelhead", "size": "Adult", "note": "Hatchery fish. Fin-clip required."},
            {**base, "river": "North Santiam River", "location": "Mehama / Lyons area", "species": "Rainbow Trout", "size": "8–10 inch", "note": "Spring stocking run."},
            {**base, "river": "Clackamas River", "location": "Barton Park", "species": "Rainbow Trout", "size": "10–12 inch", "note": "Metro area stocking."},
            {**base, "river": "Henry Hagg Lake", "location": "Main Lake", "species": "Rainbow Trout", "size": "12–14 inch", "note": "Spring opener. Large fish stocked."},
        ]
    elif month in [6, 7, 8]:
        return [
            {**base, "river": "Crooked River", "location": "Below Bowman Dam", "species": "Rainbow Trout", "size": "12–14 inch", "note": "Summer tailwater stocking."},
            {**base, "river": "Lake Billy Chinook", "location": "Cove Palisades SP", "species": "Rainbow Trout", "size": "10–12 inch", "note": "Summer boat fishery."},
            {**base, "river": "Odell Lake", "location": "Trapper Creek", "species": "Kokanee", "size": "12–14 inch", "note": "Trolling kokanee mid-summer."},
        ]
    elif month in [9, 10, 11]:
        return [
            {**base, "river": "Rogue River", "location": "Grants Pass / Gold Hill", "species": "Coho Salmon", "size": "Adult", "note": "Fall coho run."},
            {**base, "river": "Wilson River", "location": "Tillamook SF access", "species": "Coho Salmon", "size": "Adult", "note": "North coast coho."},
            {**base, "river": "Sandy River", "location": "Revenue Bridge", "species": "Fall Chinook", "size": "Adult", "note": "Fall Chinook stacking in pools."},
        ]
    else:
        return [
            {**base, "river": "Sandy River", "location": "Revenue Bridge", "species": "Winter Steelhead", "size": "Adult", "note": "Peak winter run Dec–Feb."},
            {**base, "river": "Wilson River", "location": "Jones Creek / Tillamook SF", "species": "Winter Steelhead", "size": "Adult", "note": "Winter steel."},
            {**base, "river": "North Umpqua River", "location": "Roseburg / Glide area", "species": "Winter Steelhead", "size": "Adult", "note": "Hatchery fish below Rock Creek."},
        ]


def build_river_summary(flows: dict, stocking: list) -> list:
    stocked_rivers = {s["river"] for s in stocking}
    summary = []
    for river, coords in RIVER_COORDS.items():
        flow_data = flows.get(river, {})
        cfs = flow_data.get("cfs") if isinstance(flow_data, dict) else None
        source = flow_data.get("source", "unknown") if isinstance(flow_data, dict) else "unknown"
        is_estimated = source == "spring_fed_estimate"
        condition = get_condition(river, cfs)
        if is_estimated:
            condition = {"status": "good", "color": "green", "label": "Spring-Fed — Stable", "emoji": "💧"}
        tenkara = get_tenkara_score(river, cfs)
        last_updated = flow_data.get("datetime", "N/A") if isinstance(flow_data, dict) else "N/A"
        temp_f = flow_data.get("temp_f") if isinstance(flow_data, dict) else None
        temp_cond = get_temp_condition(temp_f)
        stage_ft = flow_data.get("stage_ft") if isinstance(flow_data, dict) else None
        clarity = flow_data.get("clarity") if isinstance(flow_data, dict) else get_turbidity_label(None)
        gauges = flow_data.get("gauges", []) if isinstance(flow_data, dict) else []
        primary_gauge = flow_data.get("primary_gauge") if isinstance(flow_data, dict) else None
        info = RIVER_INFO.get(river, {})
        summary.append({
            "river": river,
            "lat": coords[0],
            "lon": coords[1],
            "cfs": cfs,
            "condition": condition,
            "tenkara_score": tenkara,
            "is_tenkara": river in TENKARA_RIVERS,
            "is_stocked": river in stocked_rivers,
            "last_updated": last_updated,
            "is_estimated": is_estimated,
            "source_note": flow_data.get("note", "") if isinstance(flow_data, dict) else "",
            "temp_f": temp_f,
            "temp_condition": temp_cond,
            "stage_ft": stage_ft,
            "clarity": clarity,
            "dissolved_oxygen_mgl": flow_data.get("dissolved_oxygen_mgl") if isinstance(flow_data, dict) else None,
            "do_condition": flow_data.get("do_condition") if isinstance(flow_data, dict) else None,
            "ph": flow_data.get("ph") if isinstance(flow_data, dict) else None,
            "ph_condition": flow_data.get("ph_condition") if isinstance(flow_data, dict) else None,
            "specific_conductance_uscm": flow_data.get("specific_conductance_uscm") if isinstance(flow_data, dict) else None,
            "gauges": gauges,
            "gauge_count": len(gauges),
            "primary_gauge": primary_gauge,
            "species": info.get("species", []),
            "gear": info.get("gear", []),
            "region": info.get("region", "Oregon"),
            "season_note": info.get("season_note", ""),
            "access": info.get("access", ""),
            "regulations": info.get("regulations", "Check current ODFW regs."),
        })
    summary.sort(key=lambda x: (
        0 if x["condition"]["status"] == "good" else
        1 if x["condition"]["status"] == "fair" else
        2 if x["condition"]["status"] == "caution" else 3
    ))
    return summary


def get_turbidity_label(fnu) -> dict:
    if fnu is None:
        return {"label": "No Data", "emoji": "❓", "color": "gray", "fishing": "Unknown clarity"}
    if fnu < 5:
        return {"label": f"{fnu:.1f} FNU — Crystal Clear", "emoji": "💎", "color": "cyan", "fishing": "Sight fishing excellent."}
    elif fnu < 25:
        return {"label": f"{fnu:.1f} FNU — Clear", "emoji": "🟢", "color": "green", "fishing": "Great conditions."}
    elif fnu < 100:
        return {"label": f"{fnu:.1f} FNU — Slightly Turbid", "emoji": "🟡", "color": "yellow", "fishing": "Nymphing best."}
    elif fnu < 400:
        return {"label": f"{fnu:.1f} FNU — Turbid", "emoji": "🟠", "color": "orange", "fishing": "Poor visibility."}
    elif fnu < 1500:
        return {"label": f"{fnu:.1f} FNU — Muddy", "emoji": "🔴", "color": "red", "fishing": "Very poor clarity."}
    else:
        return {"label": f"{fnu:.0f} FNU — Flood Mud", "emoji": "⛔", "color": "darkred", "fishing": "Do not wade."}


def get_do_condition(do_mgl) -> dict:
    if do_mgl is None:
        return {"label": "No Data", "emoji": "❓", "color": "gray", "fishing": "Unknown DO"}
    if do_mgl < 3:
        return {"label": f"DO {do_mgl:.1f} mg/L — Hypoxic", "emoji": "⚠️", "color": "red", "fishing": "Fish severely stressed. Avoid fishing."}
    elif do_mgl < 5:
        return {"label": f"DO {do_mgl:.1f} mg/L — Low", "emoji": "🟠", "color": "orange", "fishing": "Fish sluggish. Handle quickly if C&R."}
    elif do_mgl < 7:
        return {"label": f"DO {do_mgl:.1f} mg/L — Adequate", "emoji": "🟡", "color": "yellow", "fishing": "Fish moderately active."}
    elif do_mgl < 9:
        return {"label": f"DO {do_mgl:.1f} mg/L — Good", "emoji": "🟢", "color": "green", "fishing": "Fish active and feeding."}
    else:
        return {"label": f"DO {do_mgl:.1f} mg/L — Excellent", "emoji": "💚", "color": "cyan", "fishing": "Prime dissolved oxygen. Fish aggressive."}


def get_ph_condition(ph) -> dict:
    if ph is None:
        return {"label": "No Data", "emoji": "❓", "color": "gray", "fishing": "Unknown pH"}
    if ph < 5.5:
        return {"label": f"pH {ph:.1f} — Acidic", "emoji": "⚠️", "color": "red", "fishing": "Toxic to fish. Avoid."}
    elif ph < 6.5:
        return {"label": f"pH {ph:.1f} — Slightly Acidic", "emoji": "🟠", "color": "orange", "fishing": "Fish may be stressed."}
    elif ph <= 8.5:
        return {"label": f"pH {ph:.1f} — Normal", "emoji": "🟢", "color": "green", "fishing": "Ideal pH range for trout/salmon."}
    elif ph <= 9.0:
        return {"label": f"pH {ph:.1f} — Alkaline", "emoji": "🟡", "color": "yellow", "fishing": "Elevated. Fish may be less active."}
    else:
        return {"label": f"pH {ph:.1f} — High Alkaline", "emoji": "🔴", "color": "red", "fishing": "Potentially toxic ammonia."}


def get_condition(river_name: str, cfs) -> dict:
    if cfs is None:
        return {"status": "unknown", "color": "gray", "label": "No Data", "emoji": "❓"}
    if river_name not in TYPICAL_RANGES:
        return {"status": "unknown", "color": "gray", "label": "No Data", "emoji": "❓"}
    _, abs_high, low_ok, high_ok = TYPICAL_RANGES[river_name]
    if cfs > abs_high:
        return {"status": "poor", "color": "red", "label": "Too High / Dangerous", "emoji": "🔴"}
    elif cfs > high_ok:
        return {"status": "caution", "color": "orange", "label": "High — Caution", "emoji": "🟠"}
    elif cfs < 20:
        return {"status": "poor", "color": "purple", "label": "Too Low", "emoji": "🟣"}
    elif low_ok <= cfs <= high_ok:
        return {"status": "good", "color": "green", "label": "Good Conditions", "emoji": "🟢"}
    else:
        return {"status": "fair", "color": "yellow", "label": "Fair — Check Trends", "emoji": "🟡"}


def get_temp_condition(temp_f) -> dict:
    if temp_f is None:
        return {"label": "No Data", "emoji": "❓", "color": "gray"}
    if temp_f < 35:
        return {"label": f"{temp_f:.0f}°F — Too Cold", "emoji": "🥶", "color": "blue"}
    elif temp_f < 45:
        return {"label": f"{temp_f:.0f}°F — Cold", "emoji": "❄️", "color": "lightblue"}
    elif temp_f < 50:
        return {"label": f"{temp_f:.0f}°F — Cool", "emoji": "🟡", "color": "yellow"}
    elif temp_f <= 68:
        return {"label": f"{temp_f:.0f}°F — Ideal", "emoji": "🟢", "color": "green"}
    elif temp_f <= 75:
        return {"label": f"{temp_f:.0f}°F — Warm", "emoji": "🟠", "color": "orange"}
    else:
        return {"label": f"{temp_f:.0f}°F — HOT", "emoji": "🔴", "color": "red"}


def get_tenkara_score(river_name: str, cfs) -> str:
    if cfs is None:
        return "Unknown"
    if river_name not in TENKARA_RIVERS:
        return "Not Recommended"
    if river_name not in TYPICAL_RANGES:
        return "Unknown"
    _, _, low_ok, high_ok = TYPICAL_RANGES[river_name]
    tenkara_max = high_ok * 0.55
    tenkara_min = 15
    if tenkara_min <= cfs <= tenkara_max:
        return "Excellent"
    elif tenkara_min <= cfs <= high_ok:
        return "Fishable"
    elif cfs < tenkara_min:
        return "Too Low"
    else:
        return "Too High"


def rank_tenkara(river_summary: list) -> list:
    ranked = [r for r in river_summary if r["is_tenkara"] and r["tenkara_score"] in ("Excellent", "Fishable")]
    ranked.sort(key=lambda x: (0 if x["tenkara_score"] == "Excellent" else 1))
    return ranked


USGS_STAT_URL = "https://waterservices.usgs.gov/nwis/stat/"


@ttl_cache(ttl=3600)
def fetch_usgs_percentiles():
    site_ids = ",".join(OREGON_GAGE_IDS.values())
    results = {}
    try:
        resp = requests.get(USGS_STAT_URL, params={
            "format": "json",
            "sites": site_ids,
            "parameterCd": "00060",
            "statReportType": "daily",
            "statTypeCd": "all",
        }, timeout=12)
        resp.raise_for_status()
        data = resp.json()
        for ts in data.get("value", {}).get("timeSeries", []):
            site_code = ts["sourceInfo"]["siteCode"][0]["value"]
            values = ts.get("values", [{}])[0].get("value", [])
            if not values:
                continue
            stats = {}
            for v in values:
                stat_name = v.get("statistic", {}).get("statisticCd", "")
                try:
                    stats[stat_name] = float(v["value"])
                except (ValueError, KeyError, TypeError):
                    pass
            for river, gid in OREGON_GAGE_IDS.items():
                if gid == site_code and "P25" in stats:
                    results[river] = {
                        "site_id": site_code,
                        "p10": stats.get("P10"),
                        "p25": stats.get("P25"),
                        "p50": stats.get("P50"),
                        "p75": stats.get("P75"),
                        "p90": stats.get("P90"),
                        "mean": stats.get("MEAN"),
                        "min": stats.get("MIN"),
                        "max": stats.get("MAX"),
                    }
    except Exception as e:
        results["error"] = str(e)
    return results


def get_percentile_label(cfs, percentiles) -> dict:
    if cfs is None or not percentiles:
        return {"label": "No comparison data", "emoji": "❓", "color": "gray", "pct": None}
    p50 = percentiles.get("p50")
    p75 = percentiles.get("p75")
    p90 = percentiles.get("p90")
    p25 = percentiles.get("p25")
    p10 = percentiles.get("p10")
    if p50 is None or p25 is None or p75 is None:
        return {"label": "Insufficient historical data", "emoji": "❓", "color": "gray", "pct": None}
    if cfs >= p90:
        pct = min(99, int((cfs - p25) / (p90 - p25) * 100)) if p90 > p25 else 99
        return {"label": f"Very High — above 90th percentile", "emoji": "🔴", "color": "red", "pct": pct}
    elif cfs >= p75:
        return {"label": f"High — above 75th percentile", "emoji": "🟠", "color": "orange", "pct": 82}
    elif cfs >= p50:
        return {"label": f"Normal — above median", "emoji": "🟢", "color": "green", "pct": 62}
    elif cfs >= p25:
        return {"label": f"Below normal — above 25th percentile", "emoji": "🟡", "color": "yellow", "pct": 37}
    elif cfs >= p10:
        return {"label": f"Low — below 25th percentile", "emoji": "🟠", "color": "orange", "pct": 17}
    else:
        return {"label": f"Very Low — below 10th percentile", "emoji": "🔴", "color": "red", "pct": 5}

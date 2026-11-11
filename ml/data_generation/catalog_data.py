"""Word lists for realistic master data. All brands and companies are fictional."""

# Category -> (SKU prefix, share of the catalog, cost as share of price (min, max), brands)
CATEGORY_SPECS: dict[str, tuple[str, float, tuple[float, float], tuple[str, ...]]] = {
    "Laptops": ("LAP", 0.08, (0.70, 0.82), ("Lumio", "Novatek", "Cirrus", "Brightway")),
    "Electronics": ("ELE", 0.12, (0.60, 0.75), ("Sonora", "Vexo", "Lumio", "Pixelon")),
    "Accessories": ("ACC", 0.16, (0.35, 0.55), ("Ergon", "Clicko", "Linkwell", "Novatek")),
    "Office Supplies": ("OFF", 0.14, (0.40, 0.60), ("Paperline", "Scriba", "Deskwise")),
    "Automotive Parts": ("AUT", 0.13, (0.50, 0.68), ("Voltix", "Motoris", "Carvo", "Roadmax")),
    "Tools & Hardware": ("TOO", 0.13, (0.45, 0.62), ("Climbex", "Forgeline", "Ferrum")),
    "Home & Kitchen": ("HOM", 0.14, (0.42, 0.60), ("Casa", "Cucina", "Domi", "Heimwerk")),
    "Food & Beverages": ("FOO", 0.10, (0.62, 0.80), ("Bohnenhof", "Alpenquell", "Gutfeld")),
}
PARENT_CATEGORY = {"Laptops": "Electronics", "Accessories": "Electronics"}
CATEGORY_DESCRIPTIONS = {
    "Electronics": "Monitors, tablets, audio and other devices",
    "Laptops": "Notebooks for business, study and gaming",
    "Accessories": "Mice, keyboards, hubs, bags and cables",
    "Office Supplies": "Paper, writing, filing and office furniture",
    "Automotive Parts": "Batteries, oils, filters and wear parts",
    "Tools & Hardware": "Power tools, hand tools and fasteners",
    "Home & Kitchen": "Small appliances, cookware and household goods",
    "Food & Beverages": "Coffee, drinks, pantry and chilled food",
}

# Category -> items: (name, weight kg (min, max), size cm (L, W, H), price € (min, max),
#                     storage zone type)
ProductTemplate = tuple[str, tuple[float, float], tuple[float, float, float], tuple[int, int], str]
PRODUCT_TEMPLATES: dict[str, tuple[ProductTemplate, ...]] = {
    "Laptops": (
        ('Laptop 14"', (1.3, 1.7), (32, 22, 2.0), (600, 1400), "picking"),
        ('Laptop 16"', (1.9, 2.6), (36, 25, 2.2), (900, 2200), "picking"),
        ('Ultrabook 13"', (1.0, 1.3), (30, 21, 1.5), (800, 1800), "picking"),
        ('Gaming Laptop 17"', (2.6, 3.4), (40, 28, 2.8), (1200, 2800), "picking"),
        ('Convertible 14"', (1.3, 1.6), (32, 22, 1.8), (700, 1500), "picking"),
    ),
    "Electronics": (
        ('Monitor 24"', (3.2, 4.5), (60, 20, 42), (130, 280), "picking"),
        ('Monitor 27"', (4.5, 6.5), (68, 22, 48), (220, 480), "picking"),
        ('Tablet 10"', (0.4, 0.6), (26, 18, 1.2), (180, 650), "picking"),
        ("Bluetooth Speaker", (0.4, 1.2), (20, 9, 9), (35, 180), "picking"),
        ("Smart Watch", (0.05, 0.1), (5, 4, 1.2), (90, 420), "picking"),
        ("Noise-cancelling Headphones", (0.25, 0.35), (20, 18, 8), (80, 350), "picking"),
    ),
    "Accessories": (
        ("Wireless Mouse", (0.08, 0.12), (12, 7, 4), (15, 70), "picking"),
        ("Mechanical Keyboard", (0.7, 1.1), (44, 14, 4), (45, 160), "picking"),
        ("USB-C Hub", (0.08, 0.15), (11, 5, 1.5), (25, 90), "picking"),
        ('Laptop Bag 15"', (0.6, 1.0), (42, 31, 8), (30, 110), "picking"),
        ("Docking Station", (0.3, 0.6), (20, 8, 3), (90, 280), "picking"),
        ("Headset", (0.2, 0.35), (20, 18, 8), (35, 150), "picking"),
        ("Full HD Webcam", (0.1, 0.18), (10, 4, 4), (35, 120), "picking"),
        ("USB-C Cable 1 m", (0.03, 0.05), (10, 8, 2), (8, 25), "picking"),
        ("65 W USB-C Charger", (0.15, 0.25), (7, 7, 3), (25, 70), "picking"),
    ),
    "Office Supplies": (
        ("Copy Paper A4 80 g (500 sheets)", (2.4, 2.6), (30, 21, 5), (5, 9), "picking"),
        ("Ballpoint Pens (10 pack)", (0.1, 0.15), (16, 8, 2), (3, 9), "picking"),
        ("Notebook A5", (0.2, 0.35), (21, 15, 1.5), (3, 12), "picking"),
        ("Desk Stapler", (0.3, 0.5), (17, 6, 8), (6, 25), "picking"),
        ("Lever Arch File (5 pack)", (2.0, 2.6), (32, 29, 8), (12, 25), "picking"),
        ("LED Desk Lamp", (0.8, 1.5), (40, 18, 12), (25, 90), "picking"),
        ("Ergonomic Office Chair", (14, 19), (70, 65, 60), (160, 520), "bulk"),
        ("Sticky Notes (12 pack)", (0.25, 0.4), (16, 8, 8), (6, 14), "picking"),
    ),
    "Automotive Parts": (
        ("Car Battery 12 V 70 Ah", (16, 21), (28, 17.5, 19), (85, 180), "hazardous"),
        ("Engine Oil 5W-30 5 L", (4.4, 4.8), (25, 13, 32), (25, 55), "hazardous"),
        ("Oil Filter", (0.3, 0.6), (10, 10, 12), (6, 18), "picking"),
        ("Wiper Blades (pair)", (0.3, 0.5), (70, 8, 4), (12, 35), "picking"),
        ("Brake Pad Set", (1.4, 2.2), (17, 11, 8), (25, 80), "picking"),
        ("Spark Plugs (4 pack)", (0.2, 0.3), (12, 8, 3), (12, 38), "picking"),
        ('Winter Tyre 16"', (8.5, 11), (65, 65, 21), (70, 160), "bulk"),
        ("Brake Cleaner Spray 500 ml", (0.4, 0.5), (7, 7, 25), (4, 9), "hazardous"),
    ),
    "Tools & Hardware": (
        ("Cordless Drill 18 V", (1.4, 2.0), (30, 26, 9), (60, 220), "picking"),
        ("Claw Hammer", (0.5, 0.8), (33, 12, 3), (10, 35), "picking"),
        ("Screwdriver Set", (0.6, 1.1), (24, 16, 4), (15, 60), "picking"),
        ("Wood Screws (500 pack)", (1.2, 1.6), (18, 11, 6), (8, 18), "picking"),
        ("Aluminium Step Ladder", (4.0, 6.5), (110, 45, 8), (45, 140), "bulk"),
        ("Hand Saw", (0.5, 0.8), (55, 15, 3), (12, 35), "picking"),
        ("Measuring Tape 5 m", (0.2, 0.35), (8, 8, 4), (6, 20), "picking"),
        ("Drill Bit Set", (0.4, 0.9), (20, 10, 3), (12, 45), "picking"),
    ),
    "Home & Kitchen": (
        ("Electric Kettle 1.7 L", (0.9, 1.3), (24, 16, 25), (20, 70), "picking"),
        ("2-Slice Toaster", (1.2, 1.8), (30, 18, 20), (25, 80), "picking"),
        ("Blender 1.5 L", (2.0, 3.2), (20, 20, 40), (35, 140), "picking"),
        ("Non-stick Frying Pan 28 cm", (1.0, 1.5), (50, 29, 6), (20, 70), "picking"),
        ("Chef's Knife Set", (0.8, 1.6), (38, 14, 6), (30, 150), "picking"),
        ("Ceramic Mugs (6 pack)", (2.0, 2.6), (30, 20, 12), (15, 35), "picking"),
        ("Cordless Vacuum Cleaner", (2.8, 3.8), (115, 26, 22), (120, 380), "bulk"),
        ("Coffee Machine", (3.5, 6.0), (35, 25, 38), (60, 450), "picking"),
    ),
    "Food & Beverages": (
        ("Ground Coffee 1 kg", (1.0, 1.1), (20, 10, 8), (9, 22), "picking"),
        ("Mineral Water (6 x 1.5 L)", (9.2, 9.6), (25, 17, 33), (3, 8), "bulk"),
        ("Pasta 500 g (12 pack)", (6.0, 6.3), (30, 20, 22), (10, 24), "picking"),
        ("Dark Chocolate (20 pack)", (2.0, 2.1), (25, 18, 10), (18, 40), "picking"),
        ("Green Tea (100 bags)", (0.2, 0.25), (16, 8, 8), (4, 12), "picking"),
        ("Olive Oil 1 L", (1.0, 1.1), (8, 8, 30), (8, 18), "picking"),
        ("Fresh Milk 1 L (12 pack)", (12.4, 12.8), (30, 22, 25), (10, 18), "cold"),
        ("Greek Yogurt 500 g (8 pack)", (4.1, 4.3), (28, 18, 10), (12, 22), "cold"),
        ("Cheddar Cheese 400 g (10 pack)", (4.1, 4.3), (30, 20, 8), (25, 45), "cold"),
    ),
}

VARIANTS = (
    "Classic", "Pro", "Plus", "Lite", "Max", "Eco", "Premium", "Compact", "Studio",
    "Business", "Home", "Edition 2", "XL", "Mini", "Advance", "Select",
)  # fmt: skip

# Suppliers: name parts and (country, legal form, lead time offset days)
SUPPLIER_WORDS_1 = (
    "Nordtech", "Pacific", "OfficeLine", "AutoParts", "Steelcraft", "HomeGoods", "FreshChain",
    "Iberia", "Danube", "Baltic", "Rhine", "Alpine", "Atlas", "Meridian", "Polar", "Summit",
    "Vista", "Orion", "Harbor", "Crest", "Evergreen", "Granite", "Horizon", "Keystone",
)  # fmt: skip
SUPPLIER_WORDS_2 = (
    "Distribution", "Components", "Trading", "Supply", "Wholesale", "Industries", "Logistics",
    "Partners", "Imports", "Manufacturing", "Goods", "Solutions",
)  # fmt: skip
SUPPLIER_COUNTRIES = (
    ("Germany", "GmbH", 0),
    ("Germany", "GmbH", 0),
    ("Netherlands", "BV", 0),
    ("Italy", "SpA", 2),
    ("Poland", "Sp. z o.o.", 1),
    ("France", "SAS", 1),
    ("Spain", "SL", 2),
    ("Sweden", "AB", 2),
    ("Czechia", "s.r.o.", 1),
    ("Taiwan", "Ltd", 18),
    ("China", "Co., Ltd", 21),
)

# Customers
FIRST_NAMES = (
    "Anna", "Ben", "Clara", "David", "Elena", "Felix", "Greta", "Hannah", "Jonas", "Lena",
    "Lukas", "Marie", "Max", "Mia", "Noah", "Paul", "Sara", "Tim", "Sophie", "Emil", "Lea",
    "Finn", "Ida", "Leon", "Nora", "Omar", "Priya", "Tomasz", "Chiara", "Mateo",
)  # fmt: skip
LAST_NAMES = (
    "Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner", "Becker", "Schulz",
    "Hoffmann", "Koch", "Richter", "Klein", "Wolf", "Neumann", "Schwarz", "Braun", "Zimmermann",
    "Krüger", "Hartmann", "Lange", "Werner", "Krause", "Lehmann", "Köhler", "Kaya", "Nowak",
)  # fmt: skip
BUSINESS_KINDS = (
    "Elektro", "Bürobedarf", "Autoservice", "Haustechnik", "IT-Systeme", "Handel", "Werkstatt",
    "Gastronomie", "Medien", "Bau", "Logistik", "Praxis", "Kanzlei", "Design", "Studio",
)  # fmt: skip
BUSINESS_FORMS = ("GmbH", "GmbH", "GmbH & Co. KG", "KG", "e.K.", "AG", "OHG")
STREETS = (
    "Hauptstraße", "Bahnhofstraße", "Gartenweg", "Schillerstraße", "Goethestraße", "Lindenallee",
    "Industriestraße", "Marktplatz", "Am Hafen", "Ringstraße", "Kirchweg", "Talstraße",
)  # fmt: skip
CITIES = (  # (postal code, city, country)
    ("70173", "Stuttgart", "Germany"),
    ("80331", "München", "Germany"),
    ("10115", "Berlin", "Germany"),
    ("20095", "Hamburg", "Germany"),
    ("50667", "Köln", "Germany"),
    ("60311", "Frankfurt am Main", "Germany"),
    ("04109", "Leipzig", "Germany"),
    ("90402", "Nürnberg", "Germany"),
    ("68159", "Mannheim", "Germany"),
    ("76133", "Karlsruhe", "Germany"),
    ("01067", "Dresden", "Germany"),
    ("30159", "Hannover", "Germany"),
    ("44135", "Dortmund", "Germany"),
    ("28195", "Bremen", "Germany"),
    ("1010", "Wien", "Austria"),
    ("8001", "Zürich", "Switzerland"),
    ("1012", "Amsterdam", "Netherlands"),
    ("67000", "Strasbourg", "France"),
)

CARRIERS = (  # (code, name, transit working days, reliability)
    ("DHL", "DHL Paket", 2, 0.95),
    ("DPD", "DPD Deutschland", 2, 0.92),
    ("UPS", "UPS Standard", 1, 0.96),
    ("GLS", "GLS Germany", 2, 0.90),
    ("HERMES", "Hermes Germany", 3, 0.85),
    ("FEDEX", "FedEx Economy", 1, 0.97),
)

WAREHOUSES = (  # (code, name, address)
    ("WH01", "Main Distribution Centre", "Logistikstraße 12, 70173 Stuttgart, Germany"),
    ("WH02", "North Hub", "Hafenstraße 40, 20457 Hamburg, Germany"),
    ("WH03", "East Hub", "Am Güterbahnhof 7, 04129 Leipzig, Germany"),
)

# Zones in the order they are used; "returns" is always added as the last zone.
# (code, name, zone type, distance of the first rack to packing in metres)
ZONE_SPECS = (
    ("ZA", "Picking A (fast movers)", "picking", 5),
    ("ZB", "Bulk storage", "bulk", 60),
    ("ZC", "Cold storage", "cold", 35),
    ("ZH", "Hazardous goods", "hazardous", 80),
    ("ZP", "Picking B", "picking", 30),
)
RETURNS_ZONE = ("ZR", "Returns", "returns", 10)

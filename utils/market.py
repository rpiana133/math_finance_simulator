from __future__ import annotations

import threading
import time
from typing import Any

import pandas as pd
import yfinance as yf
from cachetools import TTLCache


class _TokenBucket:
    """Simple token-bucket rate limiter (thread-safe). Allows bursts up to
    *capacity* then refills at *rate* tokens/sec."""

    def __init__(self, capacity: int = 5, rate: float = 2.0):
        self.capacity = capacity
        self.rate = rate
        self._tokens = float(capacity)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._last = now
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
                wait = (1.0 - self._tokens) / self.rate
            if time.monotonic() + wait > deadline:
                return False
            time.sleep(min(wait, 0.5))


_yf_limiter = _TokenBucket(capacity=5, rate=2.0)


def _rate_limited(func, *args, **kwargs):
    """Call *func* while respecting the global yfinance rate limit.
    Retries on transient/empty responses (rate-limit indication)."""
    import logging
    logger = logging.getLogger(__name__)
    for attempt in range(3):
        _yf_limiter.acquire()
        try:
            result = func(*args, **kwargs)
            return result
        except Exception:
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    return func(*args, **kwargs)

_cache_600 = TTLCache(maxsize=2048, ttl=600)
_cache_86400 = TTLCache(maxsize=64, ttl=86400)
_cache_1800 = TTLCache(maxsize=128, ttl=1800)

POPULAR_STOCKS = {
    "MMM": "3M",
    "AOS": "A. O. Smith",
    "ABT": "Abbott Laboratories",
    "ABBV": "AbbVie",
    "ACN": "Accenture",
    "ADBE": "Adobe Inc.",
    "AMD": "Advanced Micro Devices",
    "AES": "AES Corporation",
    "AFL": "Aflac",
    "A": "Agilent Technologies",
    "APD": "Air Products",
    "ABNB": "Airbnb",
    "AKAM": "Akamai Technologies",
    "ALB": "Albemarle Corporation",
    "ARE": "Alexandria Real Estate Equities",
    "ARM": "Arm Holdings",
    "ALGN": "Align Technology",
    "ALLE": "Allegion",
    "LNT": "Alliant Energy",
    "ALL": "Allstate",
    "GOOGL": "Alphabet Inc. (Class A)",
    "GOOG": "Alphabet Inc. (Class C)",
    "MO": "Altria",
    "AMZN": "Amazon",
    "AMCR": "Amcor",
    "AEE": "Ameren",
    "AEP": "American Electric Power",
    "AXP": "American Express",
    "AIG": "American International Group",
    "AMT": "American Tower",
    "AWK": "American Water Works",
    "AMP": "Ameriprise Financial",
    "AME": "Ametek",
    "AMGN": "Amgen",
    "APH": "Amphenol",
    "ADI": "Analog Devices",
    "AON": "Aon plc",
    "APA": "APA Corporation",
    "APO": "Apollo Global Management",
    "AAPL": "Apple Inc.",
    "AMAT": "Applied Materials",
    "APP": "AppLovin",
    "APTV": "Aptiv",
    "ACGL": "Arch Capital Group",
    "ADM": "Archer Daniels Midland",
    "ARES": "Ares Management",
    "ANET": "Arista Networks",
    "AJG": "Arthur J. Gallagher & Co.",
    "AIZ": "Assurant",
    "T": "AT&T",
    "ATO": "Atmos Energy",
    "ADSK": "Autodesk",
    "ADP": "Automatic Data Processing",
    "AZO": "AutoZone",
    "AVB": "AvalonBay Communities",
    "AVY": "Avery Dennison",
    "AXON": "Axon Enterprise",
    "BKR": "Baker Hughes",
    "BALL": "Ball Corporation",
    "BAC": "Bank of America",
    "BAX": "Baxter International",
    "BDX": "Becton Dickinson",
    "BRK.B": "Berkshire Hathaway",
    "BBY": "Best Buy",
    "TECH": "Bio-Techne",
    "BIIB": "Biogen",
    "BLK": "BlackRock",
    "BX": "Blackstone Inc.",
    "XYZ": "Block, Inc.",
    "BNY": "BNY Mellon",
    "BA": "Boeing",
    "BKNG": "Booking Holdings",
    "BSX": "Boston Scientific",
    "BMY": "Bristol Myers Squibb",
    "AVGO": "Broadcom",
    "BR": "Broadridge Financial Solutions",
    "BRO": "Brown & Brown",
    "BF.B": "Brown–Forman",
    "BLDR": "Builders FirstSource",
    "BG": "Bunge Global",
    "BXP": "BXP, Inc.",
    "CHRW": "C.H. Robinson",
    "CDNS": "Cadence Design Systems",
    "CPT": "Camden Property Trust",
    "CPB": "Campbell's Company (The)",
    "COF": "Capital One",
    "CAH": "Cardinal Health",
    "CCL": "Carnival Corporation",
    "CARR": "Carrier Global",
    "CVNA": "Carvana",
    "CASY": "Casey's",
    "CAT": "Caterpillar Inc.",
    "CBOE": "Cboe Global Markets",
    "CBRE": "CBRE Group",
    "CDW": "CDW Corporation",
    "COR": "Cencora",
    "CNC": "Centene Corporation",
    "CNP": "CenterPoint Energy",
    "CF": "CF Industries",
    "CRL": "Charles River Laboratories",
    "SCHW": "Charles Schwab Corporation",
    "CHTR": "Charter Communications",
    "CVX": "Chevron Corporation",
    "CMG": "Chipotle Mexican Grill",
    "CB": "Chubb Limited",
    "CHD": "Church & Dwight",
    "CIEN": "Ciena",
    "CI": "Cigna",
    "CINF": "Cincinnati Financial",
    "CTAS": "Cintas",
    "CSCO": "Cisco",
    "C": "Citigroup",
    "CFG": "Citizens Financial Group",
    "CLX": "Clorox",
    "CME": "CME Group",
    "CMS": "CMS Energy",
    "KO": "Coca-Cola Company (The)",
    "CTSH": "Cognizant",
    "COHR": "Coherent Corp.",
    "COIN": "Coinbase",
    "CL": "Colgate-Palmolive",
    "CMCSA": "Comcast",
    "FIX": "Comfort Systems USA",
    "CAG": "Conagra Brands",
    "COP": "ConocoPhillips",
    "ED": "Consolidated Edison",
    "STZ": "Constellation Brands",
    "CEG": "Constellation Energy",
    "COO": "Cooper Companies (The)",
    "CPRT": "Copart",
    "GLW": "Corning Inc.",
    "CPAY": "Corpay",
    "CTVA": "Corteva",
    "CSGP": "CoStar Group",
    "COST": "Costco",
    "CRH": "CRH plc",
    "CRWD": "CrowdStrike",
    "CCI": "Crown Castle",
    "CSX": "CSX Corporation",
    "CMI": "Cummins",
    "CVS": "CVS Health",
    "DHR": "Danaher Corporation",
    "DRI": "Darden Restaurants",
    "DDOG": "Datadog",
    "DVA": "DaVita",
    "DECK": "Deckers Brands",
    "DE": "Deere & Company",
    "DELL": "Dell Technologies",
    "DAL": "Delta Air Lines",
    "DVN": "Devon Energy",
    "DXCM": "Dexcom",
    "FANG": "Diamondback Energy",
    "DLR": "Digital Realty",
    "DG": "Dollar General",
    "DLTR": "Dollar Tree",
    "D": "Dominion Energy",
    "DPZ": "Domino's",
    "DASH": "DoorDash",
    "DOV": "Dover Corporation",
    "DOW": "Dow Inc.",
    "DHI": "D. R. Horton",
    "DTE": "DTE Energy",
    "DUK": "Duke Energy",
    "DD": "DuPont",
    "ETN": "Eaton Corporation",
    "EBAY": "eBay Inc.",
    "SATS": "EchoStar",
    "ECL": "Ecolab",
    "EIX": "Edison International",
    "EW": "Edwards Lifesciences",
    "EA": "Electronic Arts",
    "ELV": "Elevance Health",
    "EME": "Emcor",
    "EMR": "Emerson Electric",
    "ETR": "Entergy",
    "EOG": "EOG Resources",
    "EPAM": "EPAM Systems",
    "EQT": "EQT Corporation",
    "EFX": "Equifax",
    "EQIX": "Equinix",
    "EQR": "Equity Residential",
    "ERIE": "Erie Indemnity",
    "ESS": "Essex Property Trust",
    "EL": "Estée Lauder Companies (The)",
    "EG": "Everest Group",
    "EVRG": "Evergy",
    "ES": "Eversource Energy",
    "EXC": "Exelon",
    "EXE": "Expand Energy",
    "EXPE": "Expedia Group",
    "EXPD": "Expeditors International",
    "EXR": "Extra Space Storage",
    "XOM": "ExxonMobil",
    "FFIV": "F5, Inc.",
    "FDS": "FactSet",
    "FICO": "Fair Isaac",
    "FAST": "Fastenal",
    "FRT": "Federal Realty Investment Trust",
    "FDX": "FedEx",
    "FIS": "Fidelity National Information Services",
    "FITB": "Fifth Third Bancorp",
    "FSLR": "First Solar",
    "FE": "FirstEnergy",
    "FISV": "Fiserv",
    "F": "Ford Motor Company",
    "FTNT": "Fortinet",
    "FTV": "Fortive",
    "FOXA": "Fox Corporation (Class A)",
    "FOX": "Fox Corporation (Class B)",
    "BEN": "Franklin Resources",
    "FCX": "Freeport-McMoRan",
    "GRMN": "Garmin",
    "IT": "Gartner",
    "GE": "GE Aerospace",
    "GEHC": "GE HealthCare",
    "GEV": "GE Vernova",
    "GEN": "Gen Digital",
    "GNRC": "Generac",
    "GD": "General Dynamics",
    "GIS": "General Mills",
    "GM": "General Motors",
    "GPC": "Genuine Parts Company",
    "GILD": "Gilead Sciences",
    "GPN": "Global Payments",
    "GL": "Globe Life",
    "GDDY": "GoDaddy",
    "GS": "Goldman Sachs",
    "HAL": "Halliburton",
    "HIG": "Hartford (The)",
    "HAS": "Hasbro",
    "HCA": "HCA Healthcare",
    "DOC": "Healthpeak Properties",
    "HSIC": "Henry Schein",
    "HSY": "Hershey Company (The)",
    "HPE": "Hewlett Packard Enterprise",
    "HLT": "Hilton Worldwide",
    "HD": "Home Depot (The)",
    "HON": "Honeywell",
    "HRL": "Hormel Foods",
    "HST": "Host Hotels & Resorts",
    "HWM": "Howmet Aerospace",
    "HPQ": "HP Inc.",
    "HUBB": "Hubbell Incorporated",
    "HUM": "Humana",
    "HBAN": "Huntington Bancshares",
    "HII": "Huntington Ingalls Industries",
    "IBM": "IBM",
    "IEX": "IDEX Corporation",
    "IDXX": "Idexx Laboratories",
    "ITW": "Illinois Tool Works",
    "INCY": "Incyte",
    "IR": "Ingersoll Rand",
    "PODD": "Insulet Corporation",
    "INTC": "Intel",
    "IBKR": "Interactive Brokers",
    "ICE": "Intercontinental Exchange",
    "IFF": "International Flavors & Fragrances",
    "IP": "International Paper",
    "INTU": "Intuit",
    "ISRG": "Intuitive Surgical",
    "IVZ": "Invesco",
    "INVH": "Invitation Homes",
    "IQV": "IQVIA",
    "IRM": "Iron Mountain",
    "JBHT": "J.B. Hunt",
    "JBL": "Jabil",
    "JKHY": "Jack Henry & Associates",
    "J": "Jacobs Solutions",
    "JNJ": "Johnson & Johnson",
    "JCI": "Johnson Controls",
    "JPM": "JPMorgan Chase",
    "KVUE": "Kenvue",
    "KDP": "Keurig Dr Pepper",
    "KEY": "KeyCorp",
    "KEYS": "Keysight Technologies",
    "KMB": "Kimberly-Clark",
    "KIM": "Kimco Realty",
    "KMI": "Kinder Morgan",
    "KKR": "KKR & Co.",
    "KLAC": "KLA Corporation",
    "KHC": "Kraft Heinz",
    "KR": "Kroger",
    "LHX": "L3Harris",
    "LH": "Labcorp",
    "LRCX": "Lam Research",
    "LVS": "Las Vegas Sands",
    "LDOS": "Leidos",
    "LEN": "Lennar",
    "LII": "Lennox International",
    "LLY": "Lilly (Eli)",
    "LIN": "Linde plc",
    "LYV": "Live Nation Entertainment",
    "LMT": "Lockheed Martin",
    "L": "Loews Corporation",
    "LOW": "Lowe's",
    "LULU": "Lululemon Athletica",
    "LITE": "Lumentum",
    "LYB": "LyondellBasell",
    "MTB": "M&T Bank",
    "MPC": "Marathon Petroleum",
    "MAR": "Marriott International",
    "MRSH": "Marsh McLennan",
    "MLM": "Martin Marietta Materials",
    "MAS": "Masco",
    "MA": "Mastercard",
    "MKC": "McCormick & Company",
    "MCD": "McDonald's",
    "MCK": "McKesson Corporation",
    "MDT": "Medtronic",
    "MRK": "Merck & Co.",
    "META": "Meta Platforms",
    "MET": "MetLife",
    "MTD": "Mettler Toledo",
    "MGM": "MGM Resorts",
    "MCHP": "Microchip Technology",
    "MU": "Micron Technology",
    "MSFT": "Microsoft",
    "MAA": "Mid-America Apartment Communities",
    "MRNA": "Moderna",
    "TAP": "Molson Coors Beverage Company",
    "MDLZ": "Mondelez International",
    "MPWR": "Monolithic Power Systems",
    "MNST": "Monster Beverage",
    "MCO": "Moody's Corporation",
    "MS": "Morgan Stanley",
    "MOS": "Mosaic Company (The)",
    "MSI": "Motorola Solutions",
    "MSCI": "MSCI Inc.",
    "NDAQ": "Nasdaq, Inc.",
    "NTAP": "NetApp",
    "NFLX": "Netflix",
    "NEM": "Newmont",
    "NWSA": "News Corp (Class A)",
    "NWS": "News Corp (Class B)",
    "NEE": "NextEra Energy",
    "NKE": "Nike, Inc.",
    "NI": "NiSource",
    "NDSN": "Nordson Corporation",
    "NSC": "Norfolk Southern",
    "NTRS": "Northern Trust",
    "NOC": "Northrop Grumman",
    "NCLH": "Norwegian Cruise Line Holdings",
    "NRG": "NRG Energy",
    "NUE": "Nucor",
    "NVDA": "Nvidia",
    "NVR": "NVR, Inc.",
    "NXPI": "NXP Semiconductors",
    "ORLY": "O'Reilly Automotive",
    "OXY": "Occidental Petroleum",
    "ODFL": "Old Dominion",
    "OMC": "Omnicom Group",
    "ON": "ON Semiconductor",
    "OKE": "Oneok",
    "ORCL": "Oracle Corporation",
    "OTIS": "Otis Worldwide",
    "PCAR": "Paccar",
    "PKG": "Packaging Corporation of America",
    "PLTR": "Palantir Technologies",
    "PANW": "Palo Alto Networks",
    "PSKY": "Paramount Skydance Corporation",
    "PH": "Parker Hannifin",
    "PAYX": "Paychex",
    "PYPL": "PayPal",
    "PNR": "Pentair",
    "PEP": "PepsiCo",
    "PFE": "Pfizer",
    "PCG": "PG&E Corporation",
    "PM": "Philip Morris International",
    "PSX": "Phillips 66",
    "PNW": "Pinnacle West Capital",
    "PNC": "PNC Financial Services",
    "POOL": "Pool Corporation",
    "PPG": "PPG Industries",
    "PPL": "PPL Corporation",
    "PFG": "Principal Financial Group",
    "PG": "Procter & Gamble",
    "PGR": "Progressive Corporation",
    "PLD": "Prologis",
    "PRU": "Prudential Financial",
    "PEG": "Public Service Enterprise Group",
    "PTC": "PTC Inc.",
    "PSA": "Public Storage",
    "PHM": "PulteGroup",
    "PWR": "Quanta Services",
    "QCOM": "Qualcomm",
    "DGX": "Quest Diagnostics",
    "Q": "Qnity Electronics",
    "RL": "Ralph Lauren Corporation",
    "RJF": "Raymond James Financial",
    "RTX": "RTX Corporation",
    "O": "Realty Income",
    "REG": "Regency Centers",
    "REGN": "Regeneron Pharmaceuticals",
    "RF": "Regions Financial Corporation",
    "RSG": "Republic Services",
    "RMD": "ResMed",
    "RVTY": "Revvity",
    "HOOD": "Robinhood Markets",
    "ROK": "Rockwell Automation",
    "ROL": "Rollins, Inc.",
    "ROP": "Roper Technologies",
    "ROST": "Ross Stores",
    "RCL": "Royal Caribbean Group",
    "SPGI": "S&P Global",
    "CRM": "Salesforce",
    "SNDK": "Sandisk",
    "SBAC": "SBA Communications",
    "SLB": "Schlumberger",
    "STX": "Seagate Technology",
    "SRE": "Sempra",
    "NOW": "ServiceNow",
    "SHW": "Sherwin-Williams",
    "SPG": "Simon Property Group",
    "SWKS": "Skyworks Solutions",
    "SJM": "J.M. Smucker Company (The)",
    "SW": "Smurfit Westrock",
    "SNA": "Snap-on",
    "SOLV": "Solventum",
    "SO": "Southern Company",
    "LUV": "Southwest Airlines",
    "SWK": "Stanley Black & Decker",
    "SBUX": "Starbucks",
    "STT": "State Street Corporation",
    "STLD": "Steel Dynamics",
    "STE": "Steris",
    "SYK": "Stryker Corporation",
    "SMCI": "Supermicro",
    "SYF": "Synchrony Financial",
    "SNPS": "Synopsys",
    "SYY": "Sysco",
    "TMUS": "T-Mobile US",
    "TROW": "T. Rowe Price",
    "TTWO": "Take-Two Interactive",
    "TPR": "Tapestry, Inc.",
    "TRGP": "Targa Resources",
    "TGT": "Target Corporation",
    "TEL": "TE Connectivity",
    "TDY": "Teledyne Technologies",
    "TER": "Teradyne",
    "TSLA": "Tesla, Inc.",
    "TXN": "Texas Instruments",
    "TPL": "Texas Pacific Land Corporation",
    "TXT": "Textron",
    "TMO": "Thermo Fisher Scientific",
    "TJX": "TJX Companies",
    "TKO": "TKO Group Holdings",
    "TTD": "Trade Desk (The)",
    "TSCO": "Tractor Supply",
    "TT": "Trane Technologies",
    "TDG": "TransDigm Group",
    "TRV": "Travelers Companies (The)",
    "TRMB": "Trimble Inc.",
    "TFC": "Truist Financial",
    "TYL": "Tyler Technologies",
    "TSN": "Tyson Foods",
    "USB": "U.S. Bancorp",
    "UBER": "Uber",
    "UDR": "UDR, Inc.",
    "ULTA": "Ulta Beauty",
    "UNP": "Union Pacific Corporation",
    "UAL": "United Airlines Holdings",
    "UPS": "United Parcel Service",
    "URI": "United Rentals",
    "UNH": "UnitedHealth Group",
    "UHS": "Universal Health Services",
    "VLO": "Valero Energy",
    "VEEV": "Veeva Systems",
    "VTR": "Ventas",
    "VLTO": "Veralto",
    "VRSN": "Verisign",
    "VRSK": "Verisk Analytics",
    "VZ": "Verizon",
    "VRTX": "Vertex Pharmaceuticals",
    "VRT": "Vertiv",
    "VTRS": "Viatris",
    "VICI": "Vici Properties",
    "V": "Visa Inc.",
    "VST": "Vistra Corp.",
    "VMC": "Vulcan Materials Company",
    "WRB": "W. R. Berkley Corporation",
    "GWW": "W. W. Grainger",
    "WAB": "Wabtec",
    "WMT": "Walmart",
    "DIS": "Walt Disney Company (The)",
    "WBD": "Warner Bros. Discovery",
    "WM": "Waste Management",
    "WAT": "Waters Corporation",
    "WEC": "WEC Energy Group",
    "WFC": "Wells Fargo",
    "WELL": "Welltower",
    "WST": "West Pharmaceutical Services",
    "WDC": "Western Digital",
    "WY": "Weyerhaeuser",
    "WSM": "Williams-Sonoma, Inc.",
    "WMB": "Williams Companies",
    "WTW": "Willis Towers Watson",
    "WDAY": "Workday, Inc.",
    "WYNN": "Wynn Resorts",
    "XEL": "Xcel Energy",
    "XYL": "Xylem Inc.",
    "YUM": "Yum! Brands",
    "ZBRA": "Zebra Technologies",
    "ZBH": "Zimmer Biomet",
    "ZTS": "Zoetis",
    "AFRM": "Affirm Holdings",
    "AMC": "AMC Entertainment",
    "CELH": "Celsius Holdings",
    "CHWY": "Chewy",
    "DKNG": "DraftKings",
    "DUOL": "Duolingo",
    "GME": "GameStop",
    "LCID": "Lucid Motors",
    "ONON": "On Holding",
    "PINS": "Pinterest",
    "RBLX": "Roblox",
    "RDDT": "Reddit",
    "RIVN": "Rivian Automotive",
    "RKLB": "Rocket Lab",
    "SNAP": "Snap Inc.",
    "SOFI": "SoFi Technologies",
    "SPOT": "Spotify Technology",
    "SQ": "Block, Inc.",
    "ADDYY": "Adidas ADR",
    "ASML": "ASML Holding",
    "AZN": "AstraZeneca ADR",
    "BABA": "Alibaba Group ADR",
    "BP": "BP ADR",
    "DEO": "Diageo ADR",
    "FRCOY": "Fast Retailing / Uniqlo ADR",
    "NIO": "NIO Inc. ADR",
    "NVS": "Novartis ADR",
    "PDD": "Pinduoduo ADR",
    "SE": "Sea Limited ADR",
    "SONY": "Sony Group ADR",
    "TM": "Toyota Motor ADR",
    "TSM": "TSMC ADR",
    "UA": "Under Armour (Class C)",
    "UAA": "Under Armour (Class A)",
    "UL": "Unilever ADR",
    "SPCX": "SpaceX",
    "ASTS": "AST SpaceMobile",
    "GTLB": "GitLab",
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "SOL-USD": "Solana",
    "ACHV": "Achieve Life Sciences",
    "CBRS": "Cerebras Systems",
    "NBIS": "Nebius Group",
    "LUNR": "Intuitive Machines",
    "HIMS": "Hims & Hers",
    "NVO": "Novo Nordisk ADR",
    "SKHY": "SK Hynix ADR",
    "SSNLF": "Samsung Electronics ADR",
    "TDOC": "Teladoc Health",
    "VKTX": "Viking Therapeutics",
    "QURE": "uniQure",
    "IBRX": "ImmunityBio",
    "DFTX": "Definium Therapeutics",
    "RGNX": "REGENXBIO",
    "BOLD": "Boundless Bio",
}

POPULAR_ETFS = {
    "SPY": "S&P 500 ETF",
    "QQQ": "Nasdaq 100 ETF",
    "IWM": "Russell 2000 ETF",
    "DIA": "Dow Jones ETF",
    "VTI": "Total Stock Market ETF",
    "VOO": "S&P 500 ETF (Vanguard)",
    "BND": "Total Bond Market ETF",
    "GLD": "Gold ETF",
    "IAU": "iShares Gold Trust",
    "SGOL": "Aberdeen Physical Gold Shares",
    "BAR": "GraniteShares Gold Trust",
    "PHYS": "Sprott Physical Gold Trust",
    "GDX": "VanEck Gold Miners ETF",
    "GDXJ": "VanEck Junior Gold Miners ETF",
    "SLV": "Silver ETF",
    "EEM": "Emerging Markets ETF",
    "XLF": "Financial Sector ETF",
    "XLK": "Tech Sector ETF",
    "XLV": "Healthcare Sector ETF",
    "XLE": "Energy Sector ETF",
    "SCHD": "Dividend Equity ETF",
    "VIG": "Dividend Appreciation ETF",
    "VYM": "High Dividend Yield ETF",
    "DGRO": "Dividend Growth ETF",
    "SPYD": "S&P 500 High Dividend ETF",
    "NOBL": "Dividend Aristocrats ETF",
    "SDY": "S&P Dividend ETF",
    "DVY": "Select Dividend ETF",
    "BOTZ": "Global X Robotics & AI ETF",
    "AIQ": "Global X AI & Tech ETF",
    "ROBT": "First Trust Nasdaq AI & Robotics ETF",
    "ROBO": "Robo Global Robotics & AI ETF",
    "ARKQ": "ARK Autonomous Tech & Robotics ETF",
    "ARKW": "ARK Next Gen Internet ETF",
    "AIEQ": "Amplify AI Powered Equity ETF",
    "CHAT": "Roundhill Generative AI ETF",
    "DRAM": "Roundhill Memory ETF",
    "CHPS": "Xtrackers Semiconductor Select ETF",
    "SMH": "VanEck Semiconductor ETF",
    "SOXX": "iShares Semiconductor ETF",
    "SOXQ": "Invesco Semiconductor ETF",
    "PSI": "Invesco Dynamic Semiconductors ETF",
    "FLTW": "Franklin FTSE Taiwan ETF",
    "VWO": "Vanguard FTSE Emerging Markets ETF",
    "VEA": "Vanguard FTSE Developed Markets ETF",
    "EFA": "iShares MSCI EAFE ETF",
    "IEMG": "iShares Core MSCI Emerging Markets ETF",
    "FXI": "iShares China Large-Cap ETF",
    "EWJ": "iShares MSCI Japan ETF",
    "EWG": "iShares MSCI Germany ETF",
    "EWY": "iShares MSCI South Korea ETF",
    "EWZ": "iShares MSCI Brazil ETF",
    "INDA": "iShares MSCI India ETF",
    "KWEB": "KraneShares CSI China Internet ETF",
    "ARKK": "ARK Innovation ETF",
    "TAN": "Invesco Solar ETF",
    "ICLN": "iShares Global Clean Energy ETF",
    "XLI": "Industrial Sector ETF",
    "XLY": "Consumer Discretionary ETF",
    "XLP": "Consumer Staples ETF",
    "XLU": "Utilities Sector ETF",
    "XLB": "Materials Sector ETF",
    "XLRE": "Real Estate Sector ETF",
    "AGG": "Core US Aggregate Bond ETF",
    "FBTC": "Fidelity Wise Origin Bitcoin ETF",
    "HYG": "High Yield Corporate Bond ETF",
    "IBIT": "iShares Bitcoin Trust ETF",
    "IEF": "7-10 Year Treasury Bond ETF",
    "JEPI": "JPMorgan Equity Premium Income ETF",
    "JEPQ": "JPMorgan Nasdaq Premium Income ETF",
    "SHY": "1-3 Year Treasury Bond ETF",
    "TLT": "20+ Year Treasury Bond ETF",
    "VNQ": "Vanguard Real Estate ETF",
    "VT": "Total World Stock ETF",
    "VXUS": "Total International Stock ETF",
    "SOXL": "Direxion Daily Semiconductor Bull 3X ETF",
    "TQQQ": "ProShares UltraPro QQQ",
    "ARKX": "ARK Space & Defense Innovation ETF",
    "UFO": "Procure Space ETF",
    "SHLD": "Global X Defense Tech ETF",
    "LIT": "Global X Lithium & Battery Tech ETF",
    "BITO": "ProShares Bitcoin Strategy ETF",
    "MEMY": "Tuttle Capital Meme Stock Income Blast ETF",
    "DRIP": "Direxion Daily S&P Oil & Gas Exp. & Prod. Bear 2X Shares",
    "ARTY": "iShares Future AI & Tech ETF",
    "VHT": "Vanguard Health Care ETF",
    "IXJ": "iShares Global Healthcare ETF",
    "FHLC": "Fidelity MSCI Health Care Index ETF",
    "IYH": "iShares U.S. Healthcare ETF",
    "IBB": "iShares Biotechnology ETF",
    "XBI": "SPDR S&P Biotech ETF",
    "BNDX": "Vanguard Total International Bond ETF",
    "SCHB": "Schwab U.S. Broad Market ETF",
    "SCHX": "Schwab U.S. Large-Cap ETF",
    "SCHA": "Schwab U.S. Small-Cap ETF",
    "SCHF": "Schwab International Equity ETF",
    "SCHE": "Schwab Emerging Markets Equity ETF",
    "SCHZ": "Schwab U.S. Aggregate Bond ETF",
    "VUG": "Vanguard Growth ETF",
    "VTV": "Vanguard Value ETF",
    "VO": "Vanguard Mid-Cap ETF",
    "VB": "Vanguard Small-Cap ETF",
    "IVV": "iShares Core S&P 500 ETF",
    "IJR": "iShares Core S&P Small-Cap ETF",
    "IEFA": "iShares Core MSCI EAFE ETF",
    "LQD": "iShares Investment Grade Corporate Bond ETF",
    "TIP": "iShares TIPS Bond ETF",
    "MUB": "iShares National Muni Bond ETF",
    "SPLV": "Invesco S&P 500 Low Volatility ETF",
    "SPHQ": "Invesco S&P 500 Quality ETF",
    "RSP": "Invesco S&P 500 Equal Weight ETF",
    "SPUU": "Direxion Daily S&P 500 Bull 2X ETF",
    "SPXL": "Direxion Daily S&P 500 Bull 3X ETF",
    "SH": "ProShares Short S&P 500",
    "SDS": "ProShares UltraShort S&P 500",
    "SPXS": "Direxion Daily S&P 500 Bear 3X ETF",
    "USSG": "Xtrackers MSCI USA ESG Leaders Equity ETF",
    "ESGU": "iShares ESG Aware MSCI USA ETF",
    "SUSA": "iShares MSCI USA ESG Select ETF",
    "SPLG": "SPDR Portfolio S&P 500 ETF",
}

STOCK_TICKERS = list(POPULAR_STOCKS.keys())
ETF_TICKERS = list(POPULAR_ETFS.keys())
ALL_TICKERS = sorted(STOCK_TICKERS + ETF_TICKERS)


def _lookup_name(ticker: str) -> str | None:
    return POPULAR_STOCKS.get(ticker) or POPULAR_ETFS.get(ticker)


def get_company_name(ticker: str) -> str:
    return _lookup_name(ticker) or ticker


def format_ticker_option(ticker: str) -> str:
    name = _lookup_name(ticker)
    if name:
        return f"{ticker} — {name}"
    return ticker


_price_source: dict[str, str] = {}


def get_price_source(ticker: str) -> str | None:
    return _price_source.get(ticker)


def parse_ticker_option(display_str: str) -> str:
    return display_str.split(" —")[0].strip()


CHART_PERIODS = {
    "1d": "1 Day",
    "5d": "5 Days",
    "1mo": "1 Month",
    "3mo": "3 Months",
    "6mo": "6 Months",
    "1y": "1 Year",
    "5y": "5 Years",
    "max": "Max",
}


def _flatten_cols(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is not None and isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def _cached(key: str, cache: TTLCache, func, *args) -> Any:
    if key in cache:
        return cache[key]
    result = func(*args)
    cache[key] = result
    return result


def fetch_stock_market_data(ticker: str) -> tuple[float | None, Any, str | None]:
    key = f"price_{ticker}"
    cached = _cache_600.get(key)
    if cached is not None:
        return cached
    _yf_limiter.acquire()
    cached = _cache_600.get(key)
    if cached is not None:
        return cached
    result = _fetch_stock_market_data_impl(ticker)
    _cache_600[key] = result
    return result


def fetch_full_history(ticker: str, period: str = "3mo") -> pd.DataFrame | None:
    key = f"hist_{ticker}_{period}"
    cached = _cache_600.get(key)
    if cached is not None:
        return cached
    _yf_limiter.acquire()
    cached = _cache_600.get(key)
    if cached is not None:
        return cached
    result = _fetch_full_history_impl(ticker, period)
    _cache_600[key] = result
    return result


def get_dividends(ticker: str) -> pd.Series | None:
    key = f"div_{ticker}"
    cached = _cache_86400.get(key)
    if cached is not None:
        return cached
    _yf_limiter.acquire()
    cached = _cache_86400.get(key)
    if cached is not None:
        return cached
    result = _get_dividends_impl(ticker)
    _cache_86400[key] = result
    return result


def _fetch_current_price(ticker: str) -> float | None:
    try:
        t = yf.Ticker(ticker)
        fi = t.fast_info
        if fi.get("marketState", "") == "REGULAR":
            for key in ("lastPrice", "regularMarketPrice", "previousClose"):
                v = fi.get(key)
                if v is not None:
                    return float(v)
    except Exception:
        pass
    return None


def _fetch_stock_market_data_impl(ticker: str) -> tuple[float | None, Any, str | None]:
    try:
        company_name = get_company_name(ticker)
        current = _fetch_current_price(ticker)
        if current is not None:
            _price_source[ticker] = "live"
            return current, None, company_name
        data = None
        for period in ("5d", "1mo", "6mo"):
            data = _flatten_cols(
                yf.download(ticker, period=period, progress=False, timeout=15)
            )
            if data is not None and not data.empty:
                break
        if data is None or data.empty:
            return None, None, None
        close_series = data["Close"].squeeze().dropna()
        if close_series.empty:
            return None, None, None
        close_price = float(close_series.iloc[-1])
        _price_source[ticker] = "close"
        return close_price, None, company_name
    except Exception:
        return None, None, None


def warm_price_cache(tickers: list[str]) -> None:
    # Filter out tickers that are already cached to avoid redundant network calls
    uncached = [t for t in tickers if f"price_{t}" not in _cache_600]
    if not uncached:
        return

    # Try current price per ticker first (rate-limited)
    remaining = []
    for t in uncached:
        _yf_limiter.acquire()
        p = _fetch_current_price(t)
        if p is not None:
            _cache_600[f"price_{t}"] = (p, None, get_company_name(t))
            _price_source[t] = "live"
        else:
            remaining.append(t)
    if not remaining:
        return

    try:
        _yf_limiter.acquire()
        # Download remaining tickers in a single batch
        data = _flatten_cols(
            yf.download(" ".join(remaining), period="5d", progress=False, timeout=3)
        )
        if data.empty:
            return

        # Loop through each ticker and extract its latest price
        for t in remaining:
            try:
                if len(remaining) == 1:
                    close_df = data["Close"]
                else:
                    close_df = data["Close"][t]

                close_series = close_df.squeeze()
                valid_closes = close_series.dropna()
                if not valid_closes.empty:
                    price = float(valid_closes.iloc[-1])
                    _cache_600[f"price_{t}"] = (price, None, get_company_name(t))
                    _price_source[t] = "close"
            except Exception:
                continue
    except Exception:
        pass


def _fetch_full_history_impl(ticker: str, period: str = "3mo") -> pd.DataFrame | None:
    try:
        data = _flatten_cols(
            yf.download(ticker, period=period, progress=False, timeout=10)
        )
        if data.empty:
            return None
        return data
    except Exception:
        return None


def _get_dividends_impl(ticker: str) -> pd.Series | None:
    try:
        t = yf.Ticker(ticker)
        divs = t.dividends
        if divs is None or divs.empty:
            return None
        return divs
    except Exception:
        return None


def get_top_movers(
    tickers: list[str] | tuple[str, ...],
) -> list[tuple[str, str, float, float]]:
    key = f"movers_{hash(tuple(tickers))}"
    cached = _cache_1800.get(key)
    if cached is not None:
        return cached
    _yf_limiter.acquire()
    cached = _cache_1800.get(key)
    if cached is not None:
        return cached
    result = _get_top_movers_impl(tickers)
    _cache_1800[key] = result
    return result


def _get_top_movers_impl(
    tickers: list[str] | tuple[str, ...], max_batch: int = 50
) -> list[tuple[str, str, float, float]]:
    all_results = []
    for i in range(0, len(tickers), max_batch):
        batch = tickers[i : i + max_batch]
        try:
            _yf_limiter.acquire()
            data = yf.download(" ".join(batch), period="5d", progress=False, timeout=3)
            if data.empty:
                continue
            close_df = data["Close"]
            if len(close_df) >= 2:
                pct = close_df.pct_change().iloc[-1] * 100
                latest = close_df.iloc[-1]
            else:
                pct = pd.Series(0.0, index=close_df.columns)
                latest = close_df.iloc[-1]
            for ticker in batch:
                if ticker in latest.index and not pd.isna(latest[ticker]):
                    all_results.append(
                        (
                            ticker,
                            get_company_name(ticker),
                            float(latest[ticker]),
                            float(pct.get(ticker, 0.0)),
                        )
                    )
        except Exception:
            continue
    all_results.sort(key=lambda x: x[3], reverse=True)
    return all_results

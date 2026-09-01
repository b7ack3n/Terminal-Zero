"""Geography reference: turn canonical geo codes into readable labels.

Observations store a canonical geo code ('US', 'STATE:06', 'COUNTY:06085') so
the data stays normalized and join-able. Human names are a *reference* lookup
applied when rendering — not duplicated onto every row.

Source of the codes: US Census / FIPS state codes (the standard 2-digit state
FIPS used by QCEW area_fips). Includes the 50 states, DC, and the five
inhabited territories.
"""

from __future__ import annotations

# FIPS 2-digit state code -> (name, USPS abbreviation)
FIPS_STATE: dict[str, tuple[str, str]] = {
    "01": ("Alabama", "AL"), "02": ("Alaska", "AK"), "04": ("Arizona", "AZ"),
    "05": ("Arkansas", "AR"), "06": ("California", "CA"), "08": ("Colorado", "CO"),
    "09": ("Connecticut", "CT"), "10": ("Delaware", "DE"),
    "11": ("District of Columbia", "DC"), "12": ("Florida", "FL"),
    "13": ("Georgia", "GA"), "15": ("Hawaii", "HI"), "16": ("Idaho", "ID"),
    "17": ("Illinois", "IL"), "18": ("Indiana", "IN"), "19": ("Iowa", "IA"),
    "20": ("Kansas", "KS"), "21": ("Kentucky", "KY"), "22": ("Louisiana", "LA"),
    "23": ("Maine", "ME"), "24": ("Maryland", "MD"), "25": ("Massachusetts", "MA"),
    "26": ("Michigan", "MI"), "27": ("Minnesota", "MN"), "28": ("Mississippi", "MS"),
    "29": ("Missouri", "MO"), "30": ("Montana", "MT"), "31": ("Nebraska", "NE"),
    "32": ("Nevada", "NV"), "33": ("New Hampshire", "NH"), "34": ("New Jersey", "NJ"),
    "35": ("New Mexico", "NM"), "36": ("New York", "NY"), "37": ("North Carolina", "NC"),
    "38": ("North Dakota", "ND"), "39": ("Ohio", "OH"), "40": ("Oklahoma", "OK"),
    "41": ("Oregon", "OR"), "42": ("Pennsylvania", "PA"), "44": ("Rhode Island", "RI"),
    "45": ("South Carolina", "SC"), "46": ("South Dakota", "SD"),
    "47": ("Tennessee", "TN"), "48": ("Texas", "TX"), "49": ("Utah", "UT"),
    "50": ("Vermont", "VT"), "51": ("Virginia", "VA"), "53": ("Washington", "WA"),
    "54": ("West Virginia", "WV"), "55": ("Wisconsin", "WI"), "56": ("Wyoming", "WY"),
    "60": ("American Samoa", "AS"), "66": ("Guam", "GU"),
    "69": ("Northern Mariana Islands", "MP"), "72": ("Puerto Rico", "PR"),
    "78": ("U.S. Virgin Islands", "VI"),
}


def label(geo: str | None) -> str:
    """Readable label for a canonical geo code. Unknown codes pass through."""
    if not geo:
        return "—"
    if geo == "US":
        return "United States"
    if geo.startswith("STATE:"):
        fips = geo.split(":", 1)[1]
        return FIPS_STATE.get(fips, (geo, ""))[0]
    if geo.startswith("COUNTY:"):
        # Counties aren't in the reference yet; show the code so it's honest.
        return geo
    return geo

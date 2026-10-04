"""
Countries, Indian states and phone number rules for address and contact forms.

Each country lists its dialling code and the digit counts of a phone number
without that code (mobile numbers first). Phone numbers are stored as
"+<code> <number>", which WhatsApp and the dialler both accept.
"""

import re

from django.core.exceptions import ValidationError

DEFAULT_COUNTRY = "India"

# name, dialling code, allowed digit counts without the code
_COUNTRY_DATA = """
Afghanistan|93|9
Albania|355|9
Algeria|213|9
Argentina|54|10
Armenia|374|8
Australia|61|9
Austria|43|10,11
Azerbaijan|994|9
Bahrain|973|8
Bangladesh|880|10
Belarus|375|9
Belgium|32|9
Bhutan|975|8
Bolivia|591|8
Bosnia and Herzegovina|387|8,9
Botswana|267|8
Brazil|55|10,11
Brunei|673|7
Bulgaria|359|9
Cambodia|855|8,9
Cameroon|237|9
Canada|1|10
Chile|56|9
China|86|11
Colombia|57|10
Costa Rica|506|8
Croatia|385|9
Cuba|53|8
Cyprus|357|8
Czech Republic|420|9
Denmark|45|8
Dominican Republic|1|10
Ecuador|593|9
Egypt|20|10
Estonia|372|7,8
Ethiopia|251|9
Fiji|679|7
Finland|358|9,10
France|33|9
Georgia|995|9
Germany|49|10,11
Ghana|233|9
Greece|30|10
Guyana|592|7
Hong Kong|852|8
Hungary|36|9
Iceland|354|7
India|91|10
Indonesia|62|9,10,11,12
Iran|98|10
Iraq|964|10
Ireland|353|9
Israel|972|9
Italy|39|9,10
Jamaica|1|10
Japan|81|10
Jordan|962|9
Kazakhstan|7|10
Kenya|254|9
Kuwait|965|8
Kyrgyzstan|996|9
Laos|856|9,10
Latvia|371|8
Lebanon|961|7,8
Libya|218|9
Lithuania|370|8
Luxembourg|352|9
Macau|853|8
Madagascar|261|9
Malawi|265|9
Malaysia|60|9,10
Maldives|960|7
Malta|356|8
Mauritius|230|8
Mexico|52|10
Moldova|373|8
Mongolia|976|8
Morocco|212|9
Mozambique|258|9
Myanmar|95|8,9,10
Namibia|264|9
Nepal|977|10
Netherlands|31|9
New Zealand|64|8,9,10
Nigeria|234|10
North Macedonia|389|8
Norway|47|8
Oman|968|8
Pakistan|92|10
Panama|507|8
Papua New Guinea|675|8
Paraguay|595|9
Peru|51|9
Philippines|63|10
Poland|48|9
Portugal|351|9
Qatar|974|8
Romania|40|9
Russia|7|10
Rwanda|250|9
Saudi Arabia|966|9
Senegal|221|9
Serbia|381|8,9
Seychelles|248|7
Singapore|65|8
Slovakia|421|9
Slovenia|386|8
South Africa|27|9
South Korea|82|9,10
Spain|34|9
Sri Lanka|94|9
Sudan|249|9
Suriname|597|7
Sweden|46|9
Switzerland|41|9
Syria|963|9
Taiwan|886|9
Tajikistan|992|9
Tanzania|255|9
Thailand|66|9
Trinidad and Tobago|1|10
Tunisia|216|8
Turkey|90|10
Turkmenistan|993|8
Uganda|256|9
Ukraine|380|9
United Arab Emirates|971|9
United Kingdom|44|10
United States|1|10
Uruguay|598|8
Uzbekistan|998|9
Venezuela|58|10
Vietnam|84|9
Yemen|967|9
Zambia|260|9
Zimbabwe|263|9
"""

COUNTRIES = {}
for _line in _COUNTRY_DATA.strip().splitlines():
    _name, _code, _lengths = _line.split("|")
    COUNTRIES[_name] = {"code": _code, "lengths": tuple(int(n) for n in _lengths.split(","))}

# India first, then A to Z.
COUNTRY_CHOICES = [(DEFAULT_COUNTRY, DEFAULT_COUNTRY)] + [
    (name, name) for name in sorted(COUNTRIES) if name != DEFAULT_COUNTRY
]

INDIAN_STATES = [
    "Andaman and Nicobar Islands",
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chandigarh",
    "Chhattisgarh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jammu and Kashmir",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Ladakh",
    "Lakshadweep",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Puducherry",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
]

INDIAN_STATE_CHOICES = [("", "Select state")] + [(state, state) for state in INDIAN_STATES]


def phone_rules():
    """Country -> {code, lengths}, for the form's live hint."""
    return {name: {"code": data["code"], "lengths": list(data["lengths"])} for name, data in COUNTRIES.items()}


def phone_hint(country):
    data = COUNTRIES.get(country)
    if not data:
        return ""
    lengths = " or ".join(str(n) for n in data["lengths"])
    return f"{lengths} digits, country code +{data['code']} is added for you."


def _digits_message(country, data):
    lengths = " or ".join(str(n) for n in data["lengths"])
    return f"{country} phone numbers have {lengths} digits (without +{data['code']})."


def normalize_phone(raw, country=DEFAULT_COUNTRY):
    """
    Check a phone number against the country's digit count and return it as
    "+<code> <number>". A number typed with another country's code
    ("+971 ...") is checked against that country instead. Raises
    ValidationError when the digits do not fit.
    """
    raw = (raw or "").strip()
    if not raw:
        return ""

    if re.search(r"[^\d\s+()\-./]", raw):
        raise ValidationError("Use digits only (spaces, dashes and a leading + are fine).")

    explicit = raw.startswith("+") or raw.startswith("00")
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("00"):
        digits = digits[2:]

    data = COUNTRIES.get(country) or COUNTRIES[DEFAULT_COUNTRY]
    country = country if country in COUNTRIES else DEFAULT_COUNTRY

    def fits(number, rules):
        return len(number) in rules["lengths"]

    national = None
    code = data["code"]

    if explicit:
        if digits.startswith(code) and fits(digits[len(code):], data):
            national = digits[len(code):]
        else:
            # Another country's code: longest matching code wins.
            for name, rules in sorted(COUNTRIES.items(), key=lambda item: -len(item[1]["code"])):
                if digits.startswith(rules["code"]) and fits(digits[len(rules["code"]):], rules):
                    national, code, country, data = digits[len(rules["code"]):], rules["code"], name, rules
                    break
    else:
        if fits(digits, data):
            national = digits
        elif digits.startswith("0") and fits(digits[1:], data):
            national = digits[1:]
        elif digits.startswith(code) and fits(digits[len(code):], data):
            national = digits[len(code):]

    if national is None:
        raise ValidationError(_digits_message(country, data))

    return f"+{code} {national}"

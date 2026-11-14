"""Independent reference of the seed rules (SRS section 4), used by the tests to know which addresses to expect."""

from dataclasses import dataclass

UNIQ = ("RTU IP-1", "RTU IP-2", "PLC IP-1", "PLC IP-2", "RTU Internal IP-1", "RTU Internal IP-2", "RTU-HMI IP", "IES Moxa IP")
INFRA = ("Engg. Laptop IP", "Gateway-1", "Gateway-2")
IP_FIELDS = UNIQ + INFRA
ALL_FIELDS = ("RTU IP-1", "RTU IP-2", "PLC IP-1", "PLC IP-2", "RTU Internal IP-1", "RTU Internal IP-2", "RTU-HMI IP", "Engg. Laptop IP",
              "IES Moxa IP", "Gateway-1", "Gateway-2", "Subnet Mask", "RTU VLAN", "PLC VLAN")
COLUMNS = ("Facility Name", "GCP & Ring", "Vendor", "Date", "TSU PAN Engineer") + ALL_FIELDS
GCPS = {"HDGCP1-R1": (18, 1, "1800", "1801"), "SHGCP1-R1": (19, 1, "1810", "1811"), "HWGCP1-R1": (20, 1, "1820", "1821"), "UTGCP1-R1": (21, 1, "1830", "1831")}
YOKOGAWA_FIELDS = [
    {"field": "RTU IP-1", "net": "A", "a": 1, "b": 168}, {"field": "RTU IP-2", "net": "B", "a": 1, "b": 168},
    {"field": "PLC IP-1", "net": "A", "a": 1, "b": 84}, {"field": "PLC IP-2", "net": "B", "a": 1, "b": 84},
    {"field": "RTU Internal IP-1", "net": "A", "a": 1, "b": 0}, {"field": "RTU Internal IP-2", "net": "B", "a": 1, "b": 0},
    {"field": "RTU-HMI IP", "net": "A", "a": 1, "b": 210}, {"field": "IES Moxa IP", "net": "M", "a": 1, "b": 0},
    {"field": "Engg. Laptop IP", "net": "A", "a": 0, "b": 250}, {"field": "Gateway-1", "net": "A", "a": 0, "b": 253}, {"field": "Gateway-2", "net": "B", "a": 0, "b": 253},
]


@dataclass(frozen=True)
class Blk:
    gcp: str
    vendor: str


def block(gcp: str, vendor: str) -> Blk:
    return Blk(gcp, vendor)


def build(b: Blk, n: int) -> dict:
    o1, o2, rv, pv = GCPS[b.gcp]
    p = f"{o1}.{o2}."
    if b.vendor == "Yokogawa":
        a, bb = p + "20.", p + "21."
        r = {"RTU IP-1": f"{a}{n + 168}", "RTU IP-2": f"{bb}{n + 168}", "PLC IP-1": f"{a}{n + 84}", "PLC IP-2": f"{bb}{n + 84}",
             "RTU Internal IP-1": f"{a}{n}", "RTU Internal IP-2": f"{bb}{n}", "RTU-HMI IP": f"{a}{n + 210}", "Engg. Laptop IP": f"{a}250",
             "IES Moxa IP": f"{p}10.{n}", "Gateway-1": f"{a}253", "Gateway-2": f"{bb}253"}
    else:
        a, bb, s = p + "100.", p + "101.", 4 * (n - 1) + 1
        r = {"RTU IP-1": f"{a}{s}", "RTU IP-2": f"{a}{s + 1}", "PLC IP-1": f"{a}{s + 2}", "PLC IP-2": f"{a}{s + 3}", "RTU-HMI IP": f"{bb}{n}",
             "Engg. Laptop IP": f"{a}250", "IES Moxa IP": f"{p}11.{n}", "Gateway-1": f"{a}253", "Gateway-2": f"{bb}253"}
    r.update({"Subnet Mask": "255.255.255.0", "RTU VLAN": rv, "PLC VLAN": pv})
    return {k: r[k] for k in ALL_FIELDS if k in r}


Y = block("HDGCP1-R1", "Yokogawa")

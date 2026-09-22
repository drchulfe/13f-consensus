"""테스트용 가짜 SEC 클라이언트와 공시 조립 도우미."""
import json


class FakeSec:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url):
        self.calls.append(url)
        v = self.routes.get(url)
        if v is None or isinstance(v, bytes):
            return v
        return json.dumps(v).encode()

    def get_json(self, url):
        b = self.get(url)
        return None if b is None else json.loads(b)

    def map(self, fn, items):
        return [fn(x) for x in items]


def subs_json(name, rows):
    """rows: [(acc, form, filed, period)] → submissions JSON."""
    return {"name": name, "filings": {"recent": {
        "accessionNumber": [r[0] for r in rows], "form": [r[1] for r in rows],
        "filingDate": [r[2] for r in rows], "reportDate": [r[3] for r in rows],
        "primaryDocument": ["primary_doc.xml"] * len(rows)}, "files": []}}


def add_filing(routes, cik, acc, primary, info=None):
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/"
    items = [{"name": "primary_doc.xml", "size": str(len(primary))}]
    routes[base + "primary_doc.xml"] = primary
    if info is not None:
        items.append({"name": "infotable.xml", "size": str(len(info))})
        routes[base + "infotable.xml"] = info
    routes[base + "index.json"] = {"directory": {"item": items}}


def info_xml(rows):
    """rows: [(cusip, name, value, shares)] → 정보표 XML bytes."""
    body = "".join(
        f"<infoTable><nameOfIssuer>{n}</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>{c}</cusip>"
        f"<value>{v}</value><shrsOrPrnAmt><sshPrnamt>{s}</sshPrnamt><sshPrnamtType>SH</sshPrnamtType>"
        f"</shrsOrPrnAmt></infoTable>" for c, n, v, s in rows)
    return ('<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">'
            f"{body}</informationTable>").encode()


PRIMARY = (b'<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler"><formData><coverPage>'
           b'<reportType>13F HOLDINGS REPORT</reportType></coverPage></formData></edgarSubmission>')

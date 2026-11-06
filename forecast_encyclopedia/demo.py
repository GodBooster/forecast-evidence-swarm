"""Input fixtures are deliberately synthetic and publication is explicit."""
from pathlib import Path
from .model import new_claim, append_version, fields, load_json

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures_encyclopedia" / "claims.json"


def load_demo(path=FIXTURE):
    specs = load_json(Path(path).read_text(encoding="utf-8"))
    if type(specs) is not list:
        raise ValueError("Fixture input must be a list")
    records = []
    for spec in specs:
        fields(spec, "identity snapshots", "publication")
        if type(spec["snapshots"]) is not list or not spec["snapshots"]:
            raise ValueError("Fixture requires at least one snapshot")
        r = new_claim(spec["identity"], spec["snapshots"][0], spec.get("publication"))
        for s in spec["snapshots"][1:]:
            r = append_version(r, s)
        records.append(r)
    return records

import pytest
import yaml

from portwatch.ports import UnknownPortError, get_port, load_ports


def test_17_loads_all_three_ports():
    ports = load_ports()
    assert sorted(ports) == ["corpus_christi", "houston_ship_channel", "loop"]
    assert ports["corpus_christi"].bbox == (-97.30, 27.75, -96.95, 27.90)
    assert ports["houston_ship_channel"].bbox == (-95.30, 29.60, -94.95, 29.78)
    assert ports["loop"].bbox == (-90.15, 28.80, -89.90, 28.95)


@pytest.mark.parametrize("bbox", [[-97.0, 27.0, -97.0, 28.0], [-96.0, 27.0, -97.0, 28.0],
                                  [-97.0, 28.0, -96.0, 28.0], [-97.0, 29.0, -96.0, 28.0]])
def test_18_inverted_or_empty_bbox_raises(tmp_path, bbox):
    p = tmp_path / "ports.yaml"
    p.write_text(yaml.safe_dump({"bad": {"bbox": bbox, "notes": "x"}}))
    with pytest.raises(ValueError):
        load_ports(p)


def test_19_unknown_port_lists_valid_names():
    with pytest.raises(UnknownPortError) as e:
        get_port("nowhere")
    for name in ("corpus_christi", "houston_ship_channel", "loop"):
        assert name in str(e.value)


def test_reference_override_is_read(tmp_path):
    p = tmp_path / "ports.yaml"
    p.write_text("a:\n  bbox: [-97.0, 27.0, -96.0, 28.0]\n  notes: n\n  reference: {from: '2026-01-01T00:00:00Z', to: '2026-02-01T00:00:00Z'}\n")
    ports = load_ports(p)
    assert list(ports) == ["a"]
    port = ports["a"]
    assert (port.reference_from, port.reference_to) == ("2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z")


def ports_file(tmp_path, body):
    p = tmp_path / "ports.yaml"
    p.write_text("a:\n  bbox: [-97.0, 27.0, -96.0, 28.0]\n" + body)
    return p


@pytest.mark.parametrize("stamp", ["'2026-01-01T00:00:00'", "'2026-01-01'", "2026-01-01", "2026-01-01T00:00:00",
                                   "'yesterday'", "'2026-01-01T00:00:00+02:00'", "12"])
def test_m6_naive_or_unparseable_reference_times_are_refused(tmp_path, stamp):
    with pytest.raises(ValueError):
        load_ports(ports_file(tmp_path, f"  reference: {{from: {stamp}, to: '2026-02-01T00:00:00Z'}}\n"))


@pytest.mark.parametrize("stamp", ["'2026-01-01T00:00:00Z'", "'2026-01-01T00:00:00+00:00'", "2026-01-01T00:00:00Z",
                                   "2026-01-01T00:00:00+00:00"])
def test_m6_aware_times_are_normalised_to_z(tmp_path, stamp):
    port = load_ports(ports_file(tmp_path, f"  reference: {{from: {stamp}, to: '2026-02-01T00:00:00Z'}}\n"))["a"]
    assert (port.reference_from, port.reference_to) == ("2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z")


def test_x1_houston_excludes_the_two_airports():
    houston = load_ports()["houston_ship_channel"]
    assert [e.bbox for e in houston.exclude] == [(-95.295, 29.635, -95.262, 29.660), (-95.175, 29.600, -95.140, 29.625)]
    assert "Hobby" in houston.exclude[0].note and "Ellington" in houston.exclude[1].note
    assert load_ports()["loop"].exclude == ()


def test_x1_exclude_is_read_with_its_note(tmp_path):
    port = load_ports(ports_file(tmp_path, "  exclude:\n    - {bbox: [-96.8, 27.2, -96.5, 27.4], note: runway}\n"))["a"]
    assert [(e.bbox, e.note) for e in port.exclude] == [((-96.8, 27.2, -96.5, 27.4), "runway")]


@pytest.mark.parametrize("entry", ["{bbox: [-96.5, 27.2, -96.8, 27.4]}", "{bbox: [-96.8, 27.2, -96.5]}",
                                   "{bbox: [-96.8, 27.4, -96.5, 27.2]}", "{bbox: [-96.8, 27.2, -96.5, 95]}",
                                   "{note: no box}", "[-96.8, 27.2, -96.5, 27.4]"])
def test_x1_invalid_exclude_bbox_raises(tmp_path, entry):
    with pytest.raises(ValueError):
        load_ports(ports_file(tmp_path, f"  exclude:\n    - {entry}\n"))

"""Synthetic reference validation of case-level family/source partitions."""
from collections.abc import Sequence
from dataclasses import dataclass

PARTITIONS = {"TRAIN", "DEVELOPMENT", "SEALED_TEST"}


@dataclass(frozen=True)
class PartitionEntry:
    case_id: str
    family_id: str
    source_group: str
    partition: str


def validate_entry(entry: PartitionEntry) -> None:
    for value in (entry.case_id, entry.family_id, entry.source_group):
        if type(value) is not str or not value or value != value.strip():
            raise ValueError("Partition identities must be nonempty canonical strings")
    if entry.partition not in PARTITIONS:
        raise ValueError("Unsupported case partition")


def validate_partitions(entries: Sequence[PartitionEntry]) -> None:
    if not entries:
        raise ValueError("Partition manifest cannot be empty")
    cases: set[str] = set()
    families: dict[str, str] = {}
    sources: dict[str, str] = {}
    for entry in entries:
        validate_entry(entry)
        if entry.case_id in cases:
            raise ValueError("Duplicate case partition assignment")
        cases.add(entry.case_id)
        for identity, index in ((entry.family_id, families), (entry.source_group, sources)):
            previous = index.get(identity)
            if previous is not None and previous != entry.partition:
                raise ValueError("Family or source group crosses case partitions")
            index[identity] = entry.partition

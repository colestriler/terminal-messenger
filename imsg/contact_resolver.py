from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path


CONTACT_SOURCE_GLOB = "Sources/*/AddressBook-v22.abcddb"

PHONE_CONTACTS_QUERY = """
SELECT
  p.ZFULLNUMBER,
  r.ZFIRSTNAME,
  r.ZLASTNAME,
  r.ZNICKNAME,
  r.ZORGANIZATION,
  r.ZNAME
FROM ZABCDPHONENUMBER AS p
JOIN ZABCDRECORD AS r
  ON r.Z_PK = p.ZOWNER
WHERE p.ZFULLNUMBER IS NOT NULL
"""

EMAIL_CONTACTS_QUERY = """
SELECT
  COALESCE(e.ZADDRESSNORMALIZED, e.ZADDRESS),
  r.ZFIRSTNAME,
  r.ZLASTNAME,
  r.ZNICKNAME,
  r.ZORGANIZATION,
  r.ZNAME
FROM ZABCDEMAILADDRESS AS e
JOIN ZABCDRECORD AS r
  ON r.Z_PK = e.ZOWNER
WHERE COALESCE(e.ZADDRESSNORMALIZED, e.ZADDRESS) IS NOT NULL
"""

MESSAGING_CONTACTS_QUERY = """
SELECT
  m.ZADDRESS,
  r.ZFIRSTNAME,
  r.ZLASTNAME,
  r.ZNICKNAME,
  r.ZORGANIZATION,
  r.ZNAME
FROM ZABCDMESSAGINGADDRESS AS m
JOIN ZABCDRECORD AS r
  ON r.Z_PK = m.ZOWNER
WHERE m.ZADDRESS IS NOT NULL
"""


def default_addressbook_root() -> Path:
    return Path.home() / "Library" / "Application Support" / "AddressBook"


def normalize_phone(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    if not digits:
        return ""
    if digits.startswith("1") and len(digits) == 11:
        return digits[1:]
    return digits


def contact_display_name(row: sqlite3.Row) -> str | None:
    first = (row[1] or "").strip()
    last = (row[2] or "").strip()
    full_name = " ".join(part for part in (first, last) if part).strip()
    if full_name:
        return full_name

    for index in (3, 4, 5):
        value = (row[index] or "").strip()
        if value:
            return value
    return None


class ContactResolver:
    def __init__(self, addressbook_root: Path | None = None) -> None:
        self.addressbook_root = addressbook_root or default_addressbook_root()

    @property
    @lru_cache(maxsize=1)
    def names_by_handle(self) -> dict[str, str]:
        names: dict[str, str] = {}
        for path in sorted(self.addressbook_root.glob(CONTACT_SOURCE_GLOB)):
            self._load_source(path, names)
        return names

    def _load_source(self, db_path: Path, names: dict[str, str]) -> None:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            for query, normalizer in (
                (PHONE_CONTACTS_QUERY, normalize_phone),
                (EMAIL_CONTACTS_QUERY, lambda value: value.strip().lower()),
                (MESSAGING_CONTACTS_QUERY, lambda value: value.strip().lower()),
            ):
                try:
                    rows = connection.execute(query).fetchall()
                except sqlite3.DatabaseError:
                    continue
                for row in rows:
                    raw_value = row[0]
                    if not raw_value:
                        continue
                    display_name = contact_display_name(row)
                    if not display_name:
                        continue
                    normalized = normalizer(raw_value)
                    if normalized:
                        names.setdefault(normalized, display_name)
        finally:
            connection.close()

    def lookup(self, handle: str | None) -> str | None:
        if not handle:
            return None

        lowered = handle.strip().lower()
        if "@" in lowered:
            return self.names_by_handle.get(lowered)

        normalized_phone = normalize_phone(handle)
        if normalized_phone:
            return self.names_by_handle.get(normalized_phone)

        return self.names_by_handle.get(lowered)


"""AnkiConnect client — minimal, synchronous, stdlib-only.

AnkiConnect (addon 2055492159) exposes a JSON-RPC-ish HTTP API on
http://127.0.0.1:8765.  We implement just the calls we need:
  version, createDeck, createModel, addNote, canAddNotes, findNotes, notesInfo.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Optional


class AnkiConnectError(Exception):
    pass


class AnkiConnect:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765, timeout: float = 10.0):
        self.base = f"http://{host}:{port}"
        self.timeout = timeout

    def _request(self, action: str, params: Optional[dict] = None) -> Any:
        payload = {"action": action, "version": 6, "params": params or {}}
        req = urllib.request.Request(
            self.base,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, socket.timeout) as e:
            raise AnkiConnectError(
                f"cannot reach AnkiConnect at {self.base} — is Anki running with the "
                f"AnkiConnect addon enabled? ({e})"
            ) from e
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            raise AnkiConnectError(
                f"AnkiConnect {action}: malformed response from {self.base} ({e})"
            ) from e
        if body.get("error") is not None:
            raise AnkiConnectError(f"AnkiConnect {action}: {body['error']}")
        return body.get("result")

    # -- basics ----------------------------------------------------------
    def version(self) -> int:
        return self._request("version")

    def deck_names(self) -> list[str]:
        return self._request("deckNames")

    def create_deck(self, deck: str) -> int:
        return self._request("createDeck", {"deck": deck})

    def model_names(self) -> list[str]:
        return self._request("modelNames")

    def create_model(self, name: str, fields: list[str],
                     templates: list[dict], css: str = "") -> dict:
        return self._request("createModel", {
            "modelName": name,
            "inOrderFields": fields,
            "css": css,
            "cardTemplates": templates,
        })

    # -- notes -----------------------------------------------------------
    def add_note(self, deck: str, model: str, fields: dict[str, str],
                 tags: Optional[list[str]] = None, **extra) -> int:
        return self._request("addNote", {
            "note": {
                "deckName": deck,
                "modelName": model,
                "fields": fields,
                "tags": tags or [],
                "options": {"allowDuplicate": False},
                **extra,
            }
        })

    def can_add_notes(self, deck: str, model: str, fields_list: list[dict[str, str]],
                      tags: Optional[list[str]] = None) -> list[bool]:
        return self._request("canAddNotes", {
            "notes": [
                {"deckName": deck, "modelName": model,
                 "fields": f, "tags": tags or []}
                for f in fields_list
            ]
        })

    def find_notes(self, query: str) -> list[int]:
        return self._request("findNotes", {"query": query})

    def notes_info(self, note_ids: list[int]) -> list[dict]:
        return self._request("notesInfo", {"notes": note_ids})
from collections import deque
from dataclasses import asdict, replace
from uuid import uuid4


class HandLifecycle:
    EMPTY_SECONDS = 1.2
    SIGNAL_SECONDS = 8

    def __init__(self):
        self.active = None
        self.last_state = None
        self.last_hero = ()
        self.blank_since = None
        self.blank_samples = 0
        self.reset_until = self.zero_until = self.stack_until = -1
        self.empty_observed = False
        self.saw_board = False
        self.started_count = self.finished_count = 0
        self.recent = deque(maxlen=20)
        self.pending_records = []

    def _start(self, state, frame_id, timestamp):
        self.started_count += 1
        hand_id = uuid4().hex
        self.active = {"hand_id": hand_id, "scope_id": state.scope_id, "number": self.started_count,
                       "started_frame_id": frame_id, "started_timestamp": timestamp,
                       "partial_start": not self.empty_observed, "status": "active",
                       "finished_timestamp": None, "finished_frame_id": None, "reason": None}
        self.empty_observed = False
        self.last_hero = state.hero_cards
        self.saw_board = bool(state.board)
        self.last_state = replace(state, hand_id=hand_id, hand_status="active")
        self.reset_until = self.zero_until = self.stack_until = -1
        self.pending_records.append({**self.active, "state": asdict(self.last_state)})
        return self.last_state

    def _finish(self, frame_id, timestamp, reason):
        state = replace(self.last_state, hand_status="finished")
        record = {**self.active, "status": "finished", "finished_timestamp": timestamp,
                  "finished_frame_id": frame_id, "reason": reason, "state": asdict(state)}
        self.pending_records.append(record)
        self.recent.append({k: v for k, v in record.items() if k != "state"})
        self.finished_count += 1
        self.active = None
        return state

    def update(self, previous, observed, evidence, frame_id, timestamp):
        transitions = []
        hero_ok = evidence["hero_cards"].status in {"confirmed", "empty"}
        board_ok = evidence["board"].status in {"confirmed", "empty"}
        empty = hero_ok and board_ok and not observed.hero_cards and not observed.board
        if empty:
            if self.blank_since is None:
                self.blank_since = timestamp
            self.blank_samples += 1
        else:
            self.blank_since, self.blank_samples = None, 0
        stable_empty = empty and self.blank_samples >= 3 and timestamp - self.blank_since >= self.EMPTY_SECONDS
        if stable_empty:
            self.empty_observed = True
        if self.active:
            self.saw_board |= board_ok and bool(observed.board)
            if not self.last_hero and hero_ok and observed.hero_cards:
                self.last_hero = observed.hero_cards
            if previous.board and not observed.board and board_ok:
                self.reset_until = timestamp + self.SIGNAL_SECONDS
            pot_evidence = evidence["pot"]
            if (observed.pot == "0" and previous.pot not in {None, "0"}
                    and observed.pot_unit == previous.pot_unit and pot_evidence.status == "confirmed"):
                self.zero_until = timestamp + self.SIGNAL_SECONDS
            if any(a.stack is not None and b.stack is not None and a.stack != b.stack
                   and a.stack_unit == b.stack_unit
                   and evidence[f"players.{i}.stack"].status == "confirmed"
                   for i, (a, b) in enumerate(zip(previous.players, observed.players))):
                self.stack_until = timestamp + self.SIGNAL_SECONDS
            new_hero = hero_ok and bool(observed.hero_cards) and bool(self.last_hero) and observed.hero_cards != self.last_hero
            redeal = (new_hero and board_ok and not observed.board
                      and (self.empty_observed or timestamp <= self.reset_until
                           or timestamp <= min(self.zero_until, self.stack_until)))
            finished_empty = stable_empty and (self.saw_board or timestamp <= self.zero_until)
            if finished_empty or redeal:
                reason = "stable_empty_table" if finished_empty else "new_cards_and_reset"
                transitions.append(("HAND_FINISHED", self._finish(frame_id, timestamp, reason)))
                if redeal:
                    self.empty_observed = True
        start_visible = (bool(observed.board) and board_ok
                         or bool(observed.hero_cards) and hero_ok and board_ok and not observed.board)
        if self.active is None and start_visible:
            transitions.append(("HAND_STARTED", self._start(observed, frame_id, timestamp)))
        if self.active:
            observed = replace(observed, hand_id=self.active["hand_id"], hand_status="active")
            # Preserve the last played board while a reset is being confirmed.
            if not empty and not (timestamp <= self.reset_until and not observed.board):
                self.last_state = observed
        elif self.last_state is not None:
            # Observations after the boundary must not be attributed to the old hand.
            observed = replace(observed, hand_id=None, hand_status="unidentified")
        return observed, transitions

    def interrupt(self, reason):
        if not self.active:
            return
        record = {**self.active, "status": "incomplete", "reason": reason,
                  "state": asdict(replace(self.last_state, hand_status="incomplete"))}
        self.pending_records.append(record)
        self.active = None

    def snapshot(self):
        return {"active_hand": dict(self.active) if self.active else None,
                "started_count": self.started_count, "finished_count": self.finished_count,
                "boundary_pending": self.blank_since is not None and self.active is not None,
                "recent": list(self.recent)}

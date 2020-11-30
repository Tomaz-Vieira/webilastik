from abc import ABC, abstractmethod
from typing import List, Sequence, Optional, Callable, Generic, TypeVar, Set, Dict, Any, Tuple
import typing_extensions


class CancelledException(Exception):
    pass

class NotReadyException(Exception):
    pass

CONFIRMER = Callable[[str], bool]

def noop_confirmer(msg: str) -> bool:
    return True

SV = TypeVar('SV', covariant=True)
SLOT_REFRESHER=Callable[[CONFIRMER], Optional[SV]]
class Slot(Generic[SV]):
    def __init__(
        self,
        *,
        owner: "Applet",
        value: Optional[SV] = None,
        refresher: Optional[SLOT_REFRESHER]=None,
    ):
        self.owner = owner
        self.refresher = refresher
        self.subscribers : List["Applet"] = []
        self._value : Optional[SV] = value

    def __repr__(self) -> str:
        for field_name, field_value in self.owner.__dict__.items():
            if field_value == self:
                return f"<Slot {self.owner}.{field_name}>"
        raise Exception("Could not find self in {self.owner}")

    def take_snapshot(self) -> Optional[SV]:
        return self._value

    def restore_snaphot(self, snap: Optional[SV]):
        self._value = snap

    def get_downstream_applets(self) -> List["Applet"]:
        """Returns a list of the topologically sorted applets consuming this slot"""
        out : Set["Applet"] = set(self.subscribers)
        for applet in self.subscribers:
            out.update(applet.get_downstream_applets())
        return sorted(out)

    def subscribe(self, applet: "Applet"):
        self.subscribers.append(applet)

    def refresh(self, confirmer: CONFIRMER):
        if self.refresher is not None:
            try:
                self._value = self.refresher(confirmer)
            except NotReadyException:
                self._value = None

    def __call__(self) -> SV:
        if self._value is None:
            raise NotReadyException()
        return self._value

    def get(self, default: Optional[SV] = None) -> Optional[SV]:
        return self._value

    def set_value(self, new_value: Optional[SV], confirmer: CONFIRMER):
        old_value = self._value
        self._value = new_value
        applet_snapshots = {}
        try:
            for applet in [self.owner] + self.owner.get_downstream_applets():
                applet_snapshots[applet] = applet.take_snapshot()
                applet.refresh_derived_slots(confirmer=confirmer, provoker=self)
        except Exception:
            for applet, snap in applet_snapshots.items():
                applet.restore_snaphot(snap)
            self._value = old_value
            raise


class Applet(ABC):
    def __init__(self):
        self.owned_slots = {
            slot_name: slot
            for slot_name, slot in self.__dict__.items()
            if isinstance(slot, Slot) and slot.owner == self
        }
        self.borrowed_slots = {
            slot_name: slot
            for slot_name, slot in self.__dict__.items()
            if isinstance(slot, Slot) and slot.owner != self
        }
        self.upstream_applets : Set[Applet] = {in_slot.owner for in_slot in self.borrowed_slots.values()}
        for borrowed_slot in self.borrowed_slots.values():
            self.upstream_applets.update(borrowed_slot.owner.upstream_applets)
            borrowed_slot.subscribe(self)
        #self.refresh_derived_slots(confirmer=lambda msg: True)

    def get_downstream_applets(self) -> List["Applet"]:
        """Returns a list of the topologically sorted descendants of this applet"""
        out : Set[Applet] = set()
        for output_slot in self.owned_slots.values():
            out.update(output_slot.get_downstream_applets())
        return sorted(out)

    def __lt__(self, other: "Applet") -> bool:
        return self in other.upstream_applets

    def take_snapshot(self) -> Dict[str, Any]:
        return {slot_name: slot.take_snapshot() for slot_name, slot in self.owned_slots.items()}

    def restore_snaphot(self, snap: Dict[str, Any]):
        for slot_name, saved_value in snap.items():
            slot = self.owned_slots[slot_name]
            slot.restore_snaphot(saved_value)

    @typing_extensions.final
    def refresh_derived_slots(self, confirmer: CONFIRMER, provoker: Slot):
        self.pre_refresh(confirmer)
        for slot in self.owned_slots.values():
            if slot != provoker:
                slot.refresh(confirmer)
        self.post_refresh(confirmer)

    def pre_refresh(self, confirmer: CONFIRMER):
        pass

    def post_refresh(self, confirmer: CONFIRMER):
        pass

Item_co = TypeVar("Item_co", covariant=True)
class SequenceProviderApplet(Applet, Generic[Item_co]): #(DataSelectionApplet):
    def __init__(self, refresher: Optional[SLOT_REFRESHER]=None):
        self.items = Slot[Tuple[Item_co, ...]](owner=self, refresher=refresher)
        super().__init__()

    def _set_items(self, items: Sequence[Item_co], confirmer: CONFIRMER):
        self.items.set_value(tuple(items) if len(items) > 0 else None, confirmer=confirmer)

    def add(self, items: Sequence[Item_co], confirmer: CONFIRMER) -> None:
        current_items = self.items.get() or ()
        for item in items:
            if item in current_items:
                raise ValueError(f"{item.__class__.__name__} {item} has already been added")
        self._set_items(current_items + tuple(items), confirmer=confirmer)

    def remove_at(self, idx: int, confirmer: CONFIRMER) -> None:
        items = list(self.items())
        items.pop(idx)
        self._set_items(items, confirmer=confirmer)

    def remove(self, items: Sequence[Item_co], confirmer: CONFIRMER) -> None:
        new_items = tuple(item for item in self.items() if item not in items)
        self._set_items(new_items, confirmer=confirmer)

    def clear(self, confirmer: CONFIRMER) -> None:
        self._set_items((), confirmer=confirmer)